"""No classic quest hands its reward twice (owner 2026-10-11: two Belts of Animation from level 5's "Cleric Mulgrut",
two Cloudy Green Stones from level 4's "Zombie Problem", of which only one sold).

DataQuest hands every template in FinalRewardItemTemplates. From the period guides' "You receive X from <monster>!"
upstream's generator made two templates of X, a plain cq_X ("Classic quest reward ((quest item))") and a realm
cq_<realm>_X, and ten quests hand both: both as the final reward, or one on the kill step (StepItemTemplates) or a
trade (classic-quests.json) and the other as the final reward. The period gave one. deploy/bin/mob_fixes.json keeps
one: the realm template, on the kill step where the period's monster dropped it, and a trade's own output. 0.36's
reward items doubled 37 more: 0.35b had only the plain cq_X, carried only; 0.36 added the wearable cq_<realm>_X.

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
CLASSIC_QUESTS = os.path.join(DEPLOY, "..", "source", "server", "GameServer", "quests", "QuestsMgr", "ClassicQuests.cs")
sys.path.insert(0, os.path.join(DEPLOY, "bin"))

import mob_fixes  # noqa: E402
import world_fixes as wf  # noqa: E402
from tests.test_quest_reachability import EXTRA_QUESTS, TEST_WORLD, UPSTREAM_QUESTS, merge_quests  # noqa: E402

# DataQuest's eStepType. Kill, Interact, Whisper, Search and Collect hand the step's item when the step is done;
# Deliver and DeliverFinish hand it when the step starts, and its target takes it; the other finishing steps hand
# none (FinishQuest gives only the final rewards).
HANDS_ON_COMPLETION = {0, 4, 6, 8, 10}
DELIVERY = {2, 3}
COLLECT = {10, 11}
# The quests that handed one reward twice on upstream's world, and the items.
REWARDS = {20022: ["silver chain"], 20116: ["wiley's boots"], 20137: ["wyrm sleeves"], 20207: ["belt of animation"],
           20208: ["gyrg's cloak"], 20209: ["quicksilver bracer"], 20320: ["yellow silken robes"],
           20510: ["flint dirk", "flint knife", "flinthead club"], 20515: ["cloudy green stone"], 20637: ["snake charm"]}
# 0.36's items doubled 37 more. 30 hand both copies through DataQuest: the realm template is kept, as for the ten.
REALM_REWARDS = {
    20024: ["thinking cap"], 20074: ["woven grass helm"], 20078: ["stone bracer"], 20117: ["smyga's helm"],
    20124: ["ring of illbane"], 20125: ["watercast ring"], 20126: ["driftspirit cloak"], 20127: ["toe bone belt"],
    20129: ["flame helm"], 20131: ["gauntlets of the redhand"], 20133: ["stripe hide helm"], 20134: ["nimh's curse"],
    20135: ["fine sash"], 20138: ["bulbous eye"], 20139: ["agile defender"], 20142: ["boots of stealthy evasion"],
    20243: ["fagan's signet ring"], 20244: ["fagan's signet ring"], 20245: ["fagan's signet ring"],
    20246: ["fagan's signet ring"], 20375: ["helm of the aki"], 21053: ["taldos' amulet"], 21146: ["berbenet leggings"],
    21187: ["shining crown of insanity"], 21256: ["hammer of black ice"], 21352: ["yog's iron fist"],
    21371: ["puzzler's globe"], 21406: ["faerie drake hide shield"], 21425: ["unstoppered wondrous potion"],
    21466: ["dancing silk"]}
# 8 hand one copy through classic-quests.json (a grant or a trade) or a choice and the other through DataQuest: decided
# one by one (21371 has one item of each kind).
CALLED_REWARDS = {20512: ["yellow quartz"], 20975: ["perfect life stone"], 21021: ["pious ring"], 21022: ["pious ring"],
                  21263: ["vigdis's protector"], 21264: ["herbalist's hauberk of ivy", "ring of spun silk"],
                  21371: ["scurceol's bracer"], 21465: ["brack's hammer"]}
DOUBLED = set(REWARDS) | set(REALM_REWARDS) | set(CALLED_REWARDS)
# The real items upstream's grants hand on the fixed world (classic-quests.json, merged with ours): ClassicQuests'
# GrantItems hands a lost one again, so QuestGrants hands each once per character and quest (0.37 sync, review finding
# data-1). (quest ID, stage, template)
ONCE_GRANTS = {(20975, 8, "cq_perfect_life_stone"), (21021, 3, "cq_pious_ring"), (21022, 3, "cq_pious_ring"),
               (21264, 6, "cq_ring_of_spun_silk"), (21264, 17, "cq_herbalist_s_hauberk_of_ivy"),
               (21371, 6, "cq_scurceol_s_bracer"), (21465, 3, "cq_mid_brack_s_hammer")}
# Upstream's own: two delivery items of the 0.35b and 0.37b worlds that are worn (a level-4 ring, a level-7 jewel),
# which 0.36's refresh hands again on the delivery step (the needed item, the delivery). Their quests' final rewards
# are the real items (cq_alb_slith_s_tailpiece, cq_alb_demon_soul_gem). Left as upstream has them: a later decision.
UPSTREAM_REISSUED = {(20021, 2, "needed", "cq_slith_s_tail"), (20021, 2, "delivery", "cq_slith_s_tail")} | {
    (qid, 3, how, "cq_demon_soul_gem") for qid in (21502, 21503, 21504) for how in ("needed", "delivery")}


def custom_steps():
    """{quest ID: [step info]}: upstream's classic-quests.json merged with the fork's entries, as ClassicQuests.Merge
    merges them (merge_quests)."""
    with open(UPSTREAM_QUESTS, encoding="utf-8") as f:
        upstream = json.load(f)["Quests"]
    with open(EXTRA_QUESTS, encoding="utf-8") as f:
        quests = merge_quests(upstream, json.load(f)["Quests"])
    return {qid: info.get("Steps") or [] for qid, info in quests.items()}


def templates(text):
    """The template IDs of a "|"-separated column, one per stage, without a drop chance (";50")."""
    return [entry.split(";")[0].strip().lower() for entry in (text or "").split("|")]


def handed(conn, steps_of):
    """{quest ID: {item name: [how each copy is handed]}}: the items a quest hands the player and doesn't take back."""
    names = {template.lower(): name.lower() for template, name in conn.execute("SELECT Id_nb, Name FROM ItemTemplate")}
    quests = {}
    for qid, types, items, collect, final in conn.execute(
            "SELECT ID, StepType, StepItemTemplates, CollectItemTemplate, FinalRewardItemTemplates FROM DataQuest"):
        types = [int(t) if t.strip().isdigit() else -1 for t in (types or "").split("|")]
        items, collect = templates(items), templates(collect)
        steps = steps_of.get(str(qid), [])

        def custom(n):
            step = steps[n] if n < len(steps) and steps[n] else {}
            return step, step.get("Custom") or {}

        def taken_from(n, item):
            """Whether step n or a later one takes the item back: a delivery, a collection, a trade or a use."""
            for m in range(n, len(types) + 1):
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
            if item and step_type in HANDS_ON_COMPLETION and not taken_from(n + 1, item):
                kept.append((f"step {n}", item))
            step, extra = custom(n)
            kept += [(f"trade at step {n}", out.lower()) for out in (extra.get("Trades") or {}).values() if out]
            # A choice hands one of the items it offers: of those of one name (Alastriona's four Skinner's Gloves, one
            # per armour type), one counts.
            offered = {}
            for out in (extra.get("Choices") or {}).values():
                if out and out.lower() in names:
                    offered.setdefault(names[out.lower()], out.lower())
            kept += [(f"choice at step {n}", out) for out in offered.values()]
            kept += [(f"grant at step {n}", g.lower()) for g in step.get("Grant") or [] if g and not taken_from(n, g.lower())]
            given = (extra.get("Item") or "").lower()
            if extra.get("Give") and given and not taken_from(n, given):
                kept.append((f"given at step {n}", given))
        kept += [("final reward", item) for item in templates(final) if item]
        by_name = defaultdict(list)
        for how, item in kept:
            if item in names:  # DataQuest skips a template the world lacks
                by_name[names[item]].append(f"{how}: {item}")
        quests[qid] = by_name
    return quests


def handed_again(conn, steps_of):
    """[(quest ID, stage, how, template)]: each item ClassicQuests hands a player on a step again while the player has
    none (its 5 s refresh, or talking to the step's issuer): a step's "grant" (GrantItems), a custom step's "given"
    item (CheckCustomStep), a "needed" item (OnInteract, ReissueWithoutIssuer) and a "delivery" step's item
    (GiveDeliveryItem, but a first delivery back to the giver: QuestDeliveryItems.BringsToGiver); and a kill task's
    "drop" at every kill of its monster (DropForSteps)."""
    found = []
    for qid, types, items, start, targets in conn.execute(
            "SELECT ID, StepType, StepItemTemplates, StartName, TargetName FROM DataQuest"):
        types, items = (types or "").split("|"), templates(items)
        targets = [t.split(";")[0].strip().lower() for t in (targets or "").split("|")]
        for n, step_type in enumerate(types, 1):
            item = items[n - 1] if n - 1 < len(items) else ""
            back_to_giver = n == 1 and n - 1 < len(targets) and targets[0] == (start or "").strip().lower()
            if step_type.strip() in ("2", "3") and item and not back_to_giver:
                found.append((qid, n, "delivery", item))
        steps = steps_of.get(str(qid), [])
        for n, step in enumerate(steps):
            if not step:
                continue
            extra = step.get("Custom") or {}
            found += [(qid, n, "grant", g.lower()) for g in step.get("Grant") or [] if g]
            if extra.get("Give") and extra.get("Item"):
                found.append((qid, n, "given", extra["Item"].lower()))
            if step.get("NeedsItem"):
                found.append((qid, n, "needed", step["NeedsItem"].lower()))
            found += [(qid, n, "drop", d["Item"].lower()) for d in extra.get("Drops") or [] if d and d.get("Item")]
    return found


# The DataQuest columns that hand items, and the ItemTemplate columns that change only how an item looks or reads.
REWARD_COLUMNS = ("StepItemTemplates", "CollectItemTemplate", "FinalRewardItemTemplates", "OptionalRewardItemTemplates")
LOOKS = {"model", "color", "description", "extension", "emblem", "effect", "name"}


def reward_entries(clean, steps_of, fixes):
    """{quest ID: [mob_fixes entry number]} of the entries that decide what each quest hands: its own reward columns, and
    the worth (any column but how it looks) of a template it hands, on upstream's world (`clean`) or by an entry."""
    hands = defaultdict(set)
    for qid, *columns in clean.execute(f"SELECT ID, {', '.join(REWARD_COLUMNS)} FROM DataQuest"):
        for column in columns:
            hands[qid].update(t for t in templates(column) if t)
    for qid, steps in steps_of.items():
        for step in steps:
            if not step:
                continue
            extra = step.get("Custom") or {}
            given = [*(step.get("Grant") or []), step.get("NeedsItem"), extra.get("Item"),
                     *(extra.get("Trades") or {}).values(), *(extra.get("Choices") or {}).values(),
                     *(d.get("Item") for d in extra.get("Drops") or [] if d)]
            hands[int(qid)].update(item.lower() for item in given if item)
    decides = defaultdict(list)
    for n, entry in enumerate(fixes, 1):
        if entry["table"] == "DataQuest" and set(entry["set"]) & set(REWARD_COLUMNS):
            decides[int(entry["id"])].append(n)
            for values in (entry["expect"], entry["set"]):
                hands[int(entry["id"])].update(t for c in REWARD_COLUMNS for t in templates(values.get(c)) if t)
    for n, entry in enumerate(fixes, 1):
        if entry["table"] == "ItemTemplate" and {c.lower() for c in entry["set"]} - LOOKS:
            for qid, items in hands.items():
                if entry["id"].lower() in items:
                    decides[qid].append(n)
    return {qid: sorted(ns) for qid, ns in decides.items()}


def real_items(conn):
    """The templates worth having: worn (any Item_Type but 40, the backpack) or sold (a Price). QuestGrants.IsToken."""
    return {template.lower() for template, slot, price in conn.execute("SELECT Id_nb, Item_Type, Price FROM ItemTemplate")
            if slot != 40 or price > 0}


def doubled(conn, steps_of):
    """[(quest ID, item name, [how each copy is handed])] for every quest that hands the player two items of one name
    and keeps both, where one is the final reward or the item is worth having (it is worn or sells)."""
    worth = {template.lower() for template, slot, price in conn.execute("SELECT Id_nb, Item_Type, Price FROM ItemTemplate")
             if slot != 40 or price > 0}  # Item_Type 40: carried only, as quest items are
    found = []
    for qid, by_name in handed(conn, steps_of).items():
        for name, copies in sorted(by_name.items()):
            if len(copies) > 1 and any(c.startswith("final reward") or c.split(": ")[1] in worth for c in copies):
                found.append((qid, name, copies))
    return sorted(found)


class ScanTests(unittest.TestCase):
    """The scan on a tiny world of two items of one name (no world file needed)."""

    # Alastriona's Chest (20076) offers four Skinner's Gloves, one per armour type, at its last step.
    STEPS = {"1": [None, None, {"Custom": {"Kind": "choose", "Target": "Alastriona",
                                           "Choices": {"Cloth": "gloves_cloth", "Leather": "gloves_leather"}}}]}

    def world(self, final=""):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE ItemTemplate (Id_nb TEXT, Name TEXT, Item_Type INT, Price INT)")
        conn.execute("CREATE TABLE DataQuest (ID INT, StepType TEXT, StepItemTemplates TEXT, CollectItemTemplate TEXT, "
                     "FinalRewardItemTemplates TEXT)")
        conn.executemany("INSERT INTO ItemTemplate VALUES (?, 'Skinner''s Gloves', 22, 0)",
                         [("gloves_cloth",), ("gloves_leather",)])
        conn.execute("INSERT INTO DataQuest VALUES (1, '0|9', '|', '', ?)", (final,))
        self.addCleanup(conn.close)
        return conn

    def test_a_choice_hands_one_of_its_items(self):
        conn = self.world()
        self.assertEqual(handed(conn, self.STEPS)[1]["skinner's gloves"], ["choice at step 2: gloves_cloth"])
        self.assertEqual(doubled(conn, self.STEPS), [])

    def test_a_choice_beside_a_final_reward_of_its_item_is_a_double(self):
        conn = self.world(final="gloves_leather")
        self.assertEqual(doubled(conn, self.STEPS), [
            (1, "skinner's gloves", ["choice at step 2: gloves_cloth", "final reward: gloves_leather"])])


class RefreshSourceTests(unittest.TestCase):
    """ClassicQuests' refresh (every 5 s) hands a player on a step an item the step should have given and the player
    lacks. The fork's hooks in it keep it from handing an item free (source check: the refresh is private upstream code
    that needs a live player; the rules themselves are the C# helpers' unit tests)."""

    @staticmethod
    def body(signature):
        with open(CLASSIC_QUESTS, encoding="utf-8-sig") as f:
            source = f.read()
        return source.split(signature, 1)[1].split("\n        }\n", 1)[0]

    def test_the_delivery_refresh_hands_no_item_a_quest_asks_you_to_bring(self):
        # Upstream 0.36's GiveDeliveryItem hands a Deliver step's item to a player on that step who lacks it, once a
        # minute. A first delivery back to the giver is an item the giver wants the player to bring (QuestDeliveryItems.
        # BringsToGiver; UT_DataQuestDeliveryItem): 20098's bronze short sword, the Seek the Moonstone collar and the Red
        # Dagger Map would be handed free (0.37 sync).
        body = self.body("private static void GiveDeliveryItem(GamePlayer player, DataQuest quest)")
        hook = "if (QuestDeliveryItems.BringsToGiver(quest.Step, quest.TargetName, quest.DBDataQuest?.StartName)) return;"
        self.assertIn(hook, body)
        self.assertLess(body.index(hook), body.index("string id = quest.CurrentStepItemTemplate;"))

    def test_a_grant_hands_a_real_item_once(self):
        # Upstream's GrantItems hands a step's granted item to a player on the step who holds none in slots 7-249, once
        # a minute. A real item (QuestGrants.IsToken: not carried-only, or worth money) put in the account vault, sold or
        # destroyed came back every minute; QuestGrants hands it once per character and quest, remembered in the
        # character's custom parameters (UT_QuestGrants), before upstream's own check of each item (0.37 sync).
        body = self.body("private static void GrantItems(GamePlayer player, DataQuest quest, StepInfo step)")
        hook = "if (QuestGrants.HandOnce(player, quest, id, step.GrantFrom)) continue;"
        self.assertIn(hook, body)
        self.assertLess(body.index("string id = step.Grant[i];"), body.index(hook))
        self.assertLess(body.index(hook), body.index("if (string.IsNullOrEmpty(id) || player.Inventory.GetFirstItemByID(id"))


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

    def test_upstreams_world_hands_these_rewards_twice(self):
        # The check finds what the owner met: the scan behind the fix, kept so a later upstream world is checked too.
        clean = sqlite3.connect(f"file:{TEST_WORLD}?mode=ro", uri=True)
        try:
            found = doubled(clean, self.steps)
        finally:
            clean.close()
        self.assertEqual({qid for qid, _, _ in found}, DOUBLED, found)
        self.assertIn((20207, "belt of animation", ["final reward: cq_belt_of_animation",
                                                    "final reward: cq_alb_belt_of_animation"]), found)
        self.assertIn((21146, "berbenet leggings", ["final reward: cq_berbenet_leggings",
                                                    "final reward: cq_mid_berbenet_leggings"]), found)

    def test_no_quest_hands_one_reward_twice(self):
        self.assertEqual(doubled(self.conn, self.steps), [])

    def test_an_item_handed_again_is_a_quest_token(self):
        # A real item that comes back while the player has none can be had without limit: put in the account vault
        # (outside slots 7-249), sold or destroyed, it is handed again. Only grants hand one once (QuestGrants).
        real = real_items(self.conn)
        again = {(qid, n, how, item) for qid, n, how, item in handed_again(self.conn, self.steps)
                 if how != "grant" and item in real}
        self.assertEqual(again, UPSTREAM_REISSUED)

    def test_the_real_items_grants_hand_are_the_ones_quest_grants_hands_once(self):
        real = real_items(self.conn)
        grants = {(qid, n, item) for qid, n, how, item in handed_again(self.conn, self.steps) if how == "grant" and item in real}
        self.assertEqual(grants, ONCE_GRANTS)

    def test_the_entries_that_decide_one_quests_rewards_are_one_group(self):
        # mob_fixes applies each entry under its own guard: a decision of two (a carried-only copy made the reward, and
        # the quest's other copy dropped) applied half would leave two real rewards, or none. Its entries share a group,
        # which changes whole or not at all (0.37 sync).
        fixes = mob_fixes.load_data()["fixes"]
        clean = sqlite3.connect(f"file:{TEST_WORLD}?mode=ro", uri=True)
        try:
            decides = reward_entries(clean, self.steps, fixes)
        finally:
            clean.close()
        apart = {}
        for qid, numbers in sorted(decides.items()):
            names = {fixes[n - 1].get("group") for n in numbers}
            if len(numbers) > 1 and (len(names) > 1 or None in names):
                apart[qid] = [f"{fixes[n - 1]['name']} ({fixes[n - 1]['table']} {fixes[n - 1]['id']}): "
                              f"{fixes[n - 1].get('group')}" for n in numbers]
        self.assertEqual(apart, {}, "\n".join(f"{qid}: {entries}" for qid, entries in apart.items()))
        self.assertGreaterEqual(len([numbers for numbers in decides.values() if len(numbers) > 1]), 6)

    def test_the_ten_hand_their_item_once(self):
        # Once, not twice and not never: Flint Weapons hands the weapon of the chert's shape.
        quests = handed(self.conn, self.steps)
        for qid, items in REWARDS.items():
            for item in items:
                with self.subTest(qid, item=item):
                    self.assertEqual(len(quests[qid][item]), 1, quests[qid][item])

    def test_the_realm_rewards_are_handed_once_under_the_realm_template(self):
        # 0.35b's plain cq_X is a carried-only copy (Item_Type 40, level 1, no bonuses); the realm template is the item.
        quests = handed(self.conn, self.steps)
        for qid, items in REALM_REWARDS.items():
            for item in items:
                with self.subTest(qid, item=item):
                    self.assertEqual(len(quests[qid][item]), 1, quests[qid][item])
                    self.assertRegex(quests[qid][item][0], r": cq_(alb|hib|mid)_")

    def test_a_monsters_drop_comes_on_its_kill(self):
        # "Kill Smyga and you will receive Smyg's helm." (Allakhazam cquest 414, Wayback capture 2003-12-28)
        quests = handed(self.conn, self.steps)
        for qid, item, copy in ((20117, "smyga's helm", "step 1: cq_mid_smyga_s_helm"),
                                (20125, "watercast ring", "step 1: cq_mid_watercast_ring"),
                                (20131, "gauntlets of the redhand", "step 1: cq_mid_gauntlets_of_the_redhand"),
                                (20142, "boots of stealthy evasion", "step 1: cq_mid_boots_of_stealthy_evasion"),
                                (21352, "yog's iron fist", "step 6: cq_alb_yog_s_iron_fist"),
                                (21371, "puzzler's globe", "step 5: cq_alb_puzzler_s_globe"),
                                (21425, "unstoppered wondrous potion", "step 9: cq_hib_unstoppered_wondrous_potion_hib")):
            with self.subTest(qid, item=item):
                self.assertEqual(quests[qid][item], [copy])

    def test_the_called_rewards_are_handed_once(self):
        # The copy the period's guide describes: a trade's own output, an NPC's hand-over (upstream's grant), a choice.
        quests = handed(self.conn, self.steps)
        for qid, item, copy in ((20512, "yellow quartz", "trade at step 1: cq_yellow_quartz"),
                                (20975, "perfect life stone", "grant at step 8: cq_perfect_life_stone"),
                                (21021, "pious ring", "grant at step 3: cq_pious_ring"),
                                (21022, "pious ring", "grant at step 3: cq_pious_ring"),
                                (21263, "vigdis's protector", "choice at step 8: cq_mid_vigdis_s_protector"),
                                (21264, "ring of spun silk", "grant at step 6: cq_ring_of_spun_silk"),
                                (21264, "herbalist's hauberk of ivy", "grant at step 17: cq_herbalist_s_hauberk_of_ivy"),
                                (21371, "scurceol's bracer", "grant at step 6: cq_scurceol_s_bracer"),
                                (21465, "brack's hammer", "grant at step 3: cq_mid_brack_s_hammer")):
            with self.subTest(qid, item=item):
                self.assertEqual(quests[qid][item], [copy])

    def test_breaking_the_blades_journal_sends_the_player_back_for_the_belt_at_the_end(self):
        # "4)You are then told to go kill Prince Abdin. 5)Return to Mysteras. 6) Receive a reward (belt)." (Allakhazam
        # cquest 1802, Wayback capture 2003-12-28). The belt is now the step-8 choice (the Breaking the Blade entry), so
        # stage 4's journal line no longer promises one, and stage 6 sends the player back after Legion for both rewards
        # (the crown and the belt), not "another".
        stages, items = self.conn.execute("SELECT StepText, StepItemTemplates FROM DataQuest WHERE ID=21263").fetchone()
        stages = stages.split("|")
        self.assertEqual(items, "|||||||")
        self.assertEqual(stages[3], "Return to Mystemas.")
        self.assertEqual(stages[5], "Return to Mystemas for your rewards.")
        self.assertEqual([n for n, text in enumerate(stages, 1) if "belt" in text.lower() or "another" in text.lower()], [])

    def test_a_granted_reward_is_the_period_item(self):
        # "he will reward you with a Perfect Life Stone (Necklace item with 118hp)" (Allakhazam cquest 2007, Wayback
        # capture 2004-04-19). Upstream's grant hands 0.35b's carried-only copy; it takes the realm template's values.
        columns = [c for _, c, *_ in self.conn.execute("PRAGMA table_info(ItemTemplate)")
                   if c not in ("Id_nb", "ItemTemplate_ID", "LastTimeRowUpdated")]
        select = "SELECT " + ", ".join(f'"{c}"' for c in columns) + " FROM ItemTemplate WHERE Id_nb=?"
        for granted, realm in (("cq_perfect_life_stone", "cq_hib_perfect_life_stone"),
                               ("cq_pious_ring", "cq_mid_pious_ring"),
                               ("cq_ring_of_spun_silk", "cq_mid_ring_of_spun_silk"),
                               ("cq_herbalist_s_hauberk_of_ivy", "cq_mid_herbalist_s_hauberk_of_ivy"),
                               ("cq_scurceol_s_bracer", "cq_alb_scurceol_s_bracer")):
            with self.subTest(granted):
                self.assertEqual(self.conn.execute(select, (granted,)).fetchone(),
                                 self.conn.execute(select, (realm,)).fetchone())

    def test_hilde_hands_the_hammer_itself_and_the_delivery_keeps_upstreams_copy(self):
        # "He drops a Brack's {something}. You have to return to Haggerfel and talk to Hilde. She says keep the hammer"
        # (Allakhazam cquest 114, Wayback capture 2003-12-28). Upstream's carried-only copy is also the item stage 2
        # delivers to Hilde, which a lost one is handed again for, so it stays a token, and Hilde's grant hands the
        # realm template: our Replace entry is upstream's but for that grant.
        with open(UPSTREAM_QUESTS, encoding="utf-8") as f:
            upstream = json.load(f)["Quests"]["21465"]
        with open(EXTRA_QUESTS, encoding="utf-8") as f:
            ours = json.load(f)["Quests"]["21465"]
        upstream["Steps"][3]["Grant"] = ["cq_mid_brack_s_hammer"]
        self.assertEqual(ours, {"Replace": True, **upstream})
        self.assertEqual(self.conn.execute("SELECT Item_Type, Level, Price FROM ItemTemplate WHERE Id_nb='cq_brack_s_hammer'")
                         .fetchone(), (40, 1, 0))
        self.assertEqual(self.conn.execute("SELECT Item_Type, Level FROM ItemTemplate WHERE Id_nb='cq_mid_brack_s_hammer'")
                         .fetchone(), (10, 16))

    def test_the_kept_items_delve_their_quest(self):
        # A delve's first line is the template's Description: upstream's plain templates read
        # "Classic quest reward ((quest item))".
        quests = handed(self.conn, self.steps)
        for qid, items in REWARDS.items():
            quest = self.conn.execute("SELECT Name FROM DataQuest WHERE ID=?", (qid,)).fetchone()[0]
            for item in items:
                template = quests[qid][item][0].split(": ")[1]
                with self.subTest(qid, template=template):
                    self.assertEqual(self.conn.execute("SELECT Description FROM ItemTemplate WHERE Id_nb=?",
                                                       (template,)).fetchone(), (f"Classic quest reward ({quest})",))

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

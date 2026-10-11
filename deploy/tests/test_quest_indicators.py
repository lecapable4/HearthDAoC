"""Quest indicators: one scheme for every quest, kept current (source checks).

Spec docs/fork/specs/2026-10-11-quest-indicators-design.md. GameNPC.GetQuestIndicator returns a meaning worked out by
QuestIndicators.For; the two packet writers the 1.127 client uses (PacketLib1124.SendNPCCreate, PacketLib173.
SendNPCsQuestEffect) turn it into the value the client draws and record it; a change of level, class or quests, and the
daily, weekly and monthly rollovers, ask QuestIndicators.Refresh, which sends the quest effect where a value changed.
The rules, the table and the refresh's store are unit-tested (UT_QuestIndicators, UT_IndicatorSentStore); the hooks in
upstream files need a live server, client and region, so these check the source.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GAME_SERVER = os.path.join(ROOT, "source", "server", "GameServer")
FORK = os.path.join(GAME_SERVER, "scripts", "hearthdaoc")
GAME_NPC = os.path.join(GAME_SERVER, "gameobjects", "GameNPC.cs")
GAME_PLAYER = os.path.join(GAME_SERVER, "gameobjects", "GamePlayer.cs")
CREATE = os.path.join(GAME_SERVER, "packets", "Server", "PacketLib1124.cs")
EFFECT = os.path.join(GAME_SERVER, "packets", "Server", "PacketLib173.cs")
ABSTRACT_QUEST = os.path.join(GAME_SERVER, "quests", "QuestsMgr", "AbstractQuest.cs")
DATA_QUEST = os.path.join(GAME_SERVER, "quests", "QuestsMgr", "DataQuest.cs")
DAILY = os.path.join(GAME_SERVER, "ECS-Services", "DailyQuestService.cs")
WEEKLY = os.path.join(GAME_SERVER, "ECS-Services", "WeeklyQuestService.cs")
MONTHLY = os.path.join(GAME_SERVER, "ECS-Services", "MonthlyQuestService.cs")
QUEST_INDICATORS = os.path.join(FORK, "QuestIndicators.cs")
SENT_STORE = os.path.join(FORK, "IndicatorSentStore.cs")
EPIC = os.path.join(FORK, "EpicCommand.cs")
INDICATOR = os.path.join(FORK, "IndicatorCommand.cs")


def read(path):
    """A C# source file's text (upstream files may start with a BOM; a few are not UTF-8)."""
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        return f.read()


def between(text, start, end):
    """The text from the first start up to the first end after it."""
    body = text[text.index(start):]
    return body[:body.index(end)]


def marked(test, body, call):
    """The body calls the fork once, on a line marked // HearthDAoC: (the line itself or the comment line above)."""
    test.assertEqual(body.count(call), 1, call)
    line = body[:body.index(call)].rsplit("\n", 2)
    test.assertIn("HearthDAoC:", "\n".join(line[-2:]) + body[body.index(call):].split("\n", 1)[0], call)


class RulesAndPacketsTests(unittest.TestCase):
    def test_get_quest_indicator_asks_the_gm_value_then_the_rules(self):
        body = between(read(GAME_NPC), "public virtual eQuestIndicator GetQuestIndicator(GamePlayer player)",
                       "\n\t\t}\n")
        override = body.index("HearthDAoC.IndicatorOverrides.TryGet(player, this, out eQuestIndicator forced)")
        rules = body.index("return HearthDAoC.QuestIndicators.For(this, player, scripted, offered);")
        self.assertLess(override, rules)
        self.assertIn("// HearthDAoC: one set of rules for every NPC", body)
        self.assertNotIn("CanShowOneQuest(player)", body)
        self.assertNotIn("CanFinishOneQuest(player)", body)

    def test_the_create_packet_sends_the_wire_value(self):
        body = between(read(CREATE), "public override void SendNPCCreate(GameNPC npc)", "pak.WriteByte(flags3);")
        asked = body.index("eQuestIndicator questIndicator = npc.GetQuestIndicator(m_gameClient.Player);")
        mapped = body.index("questIndicator = HearthDAoC.QuestIndicators.SendingCreate(m_gameClient.Player, npc, questIndicator);")
        first_flag = body.index("if (questIndicator == eQuestIndicator.Available)")
        self.assertLess(asked, mapped)
        self.assertLess(mapped, first_flag)
        marked(self, body, "HearthDAoC.QuestIndicators.SendingCreate(")

    def test_the_quest_effect_sends_the_wire_value(self):
        body = between(read(EFFECT), "public override void SendNPCsQuestEffect(GameNPC npc, eQuestIndicator indicator)",
                       "SendTCP(pak);")
        mapped = body.index("indicator = HearthDAoC.QuestIndicators.Sending(m_gameClient.Player, npc, indicator);")
        self.assertLess(body.index("if (m_gameClient.Player == null || npc == null)"), mapped)
        self.assertLess(mapped, body.index("pak.WriteByte((byte)indicator);"))
        marked(self, body, "HearthDAoC.QuestIndicators.Sending(")

    def test_the_refresh_runs_once_per_tick_for_a_playing_client_and_sends_what_the_writers_send(self):
        text = read(QUEST_INDICATORS)
        refresh = between(text, "public static void Refresh(GamePlayer player)", "\n    }\n")
        self.assertIn("LastSent.TryQueue(player)", refresh)
        self.assertIn("GameLoopService.Instance.Post(s_run, player);", refresh)
        run = between(text, "private static void Run(GamePlayer player)", "\n    }\n")
        # A client on a loading screen or not yet in the game gets every NPC again with its create packet.
        self.assertIn("player.Client?.ClientState != GameClient.eClientState.Playing", run)
        # The NPCs are asked with the cache lock released, and through the writers' own WireFor (a GM's /indicator
        # create value stays raw).
        self.assertLess(run.index("known = new List<GameNPC>(cache.NpcUpdateCache.Keys);"),
                        run.index("npc.GetQuestIndicator(player)"))
        self.assertIn("return (meaning, (byte)WireFor(player, npc, meaning));", run)
        # One NPC's exception keeps its marker and doesn't stop the others.
        self.assertIn("return (eQuestIndicator.None, LastSent.Last(player, npc));", run)


class EndingsTests(unittest.TestCase):
    def test_the_upstream_files_keep_their_endings_and_bom(self):
        for path, bom in ((GAME_NPC, False), (GAME_PLAYER, False), (CREATE, True), (EFFECT, False),
                          (ABSTRACT_QUEST, False), (DATA_QUEST, True), (DAILY, False), (WEEKLY, False),
                          (MONTHLY, False)):
            with open(path, "rb") as f:
                raw = f.read()
            self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"), path)
            self.assertEqual(raw.startswith(b"\xef\xbb\xbf"), bom, path)

    def test_the_fork_files_are_lf(self):
        for path in (QUEST_INDICATORS, SENT_STORE):
            with open(path, "rb") as f:
                raw = f.read()
            self.assertNotIn(b"\r", raw, path)
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), path)


class ProbeTests(unittest.TestCase):
    def test_indicator_effect_stays_raw(self):
        text = read(INDICATOR)
        self.assertIn("QuestIndicators.SendRawEffect(gm, npc, request.Effect);", text)
        self.assertNotIn("SendNPCsQuestEffect(npc, (eQuestIndicator)request.Effect)", text)


def last_statement(test, body, call, indent):
    """The hook is a statement of the method's own block, at this indentation, followed only by `return true;` and
    closing braces: not inside an if or an else, and not before the change it reports."""
    lines = body.split("\n")
    at = [i for i, line in enumerate(lines) if call in line]
    test.assertEqual(len(at), 1, call)
    line = lines[at[0]]
    test.assertEqual(line[:len(line) - len(line.lstrip())], indent, call)
    test.assertRegex("\n".join(lines[at[0] + 1:]), r"^\s*(return true;)?[\s}]*$", call)


class WiringTests(unittest.TestCase):
    """The game-facing code calls the unit-tested decisions (UT_QuestIndicators, UT_IndicatorSentStore), which can't
    reach it: it needs live players and NPCs."""

    def test_raw_values_are_decided_by_is_raw(self):
        text = read(QUEST_INDICATORS)
        self.assertIn("ToWire(value, IsRaw(t_raw, Forced(player, npc, value)))",
                      between(text, "public static eQuestIndicator WireFor(", ";\n"))
        create = between(text, "public static eQuestIndicator SendingCreate(", "\n    }\n")
        self.assertIn("bool forced = Forced(player, npc, value);", create)
        self.assertIn("ToWire(value, IsRaw(t_raw, forced))", create)

    def test_a_changed_create_asks_a_refresh_and_a_probe_value_does_not(self):
        create = between(read(QUEST_INDICATORS), "public static eQuestIndicator SendingCreate(", "\n    }\n")
        self.assertRegex(create, r"if \(LastSent\.RecordCreate\(player, npc, \(byte\)wire, "
                                 r"new SentPlace\(npc\.ObjectID, npc\.CurrentRegionID\), forced\)\)\n\s*Refresh\(player\);")

    def test_the_effect_writer_records_where_the_client_knows_the_npc(self):
        sending = between(read(QUEST_INDICATORS), "public static eQuestIndicator Sending(", "\n    }\n")
        self.assertIn("LastSent.Record(player, npc, (byte)wire, new SentPlace(npc.ObjectID, npc.CurrentRegionID));",
                      sending)

    def test_the_raw_effect_flag_is_set_and_always_cleared(self):
        body = between(read(QUEST_INDICATORS), "public static void SendRawEffect(", "\n    }\n")
        self.assertRegex(body, r"t_raw = true;\s*try\s*\{\s*player\.Out\.SendNPCsQuestEffect\(npc, \(eQuestIndicator\)value\);"
                               r"\s*\}\s*finally\s*\{\s*t_raw = false;\s*\}")

    def test_the_adapter_uses_the_tested_rules(self):
        text = read(QUEST_INDICATORS)
        adapter = between(text, "public static eQuestIndicator For(GameNPC npc, GamePlayer player,", "\n    }\n")
        offers = between(text, "private static IEnumerable<QuestOffer> Offers(", "\n    }\n")
        self.assertIn("RewardDone(rewardQuest.QuestGiver == npc, rewardQuest.Goals.Select(g => g.IsAchieved))", adapter)
        self.assertIn("yield return ScriptedOffer(ScriptedMinLevel(quest), quest.CheckQuestQualification(player),", offers)
        self.assertIn("if (DataOffer(quest.ShowIndicator, quest.Level, () => quest.CheckQuestQualification(player), "
                      "out QuestOffer offer))", offers)
        for rule in ("< quest.MaxQuestCount", "if (quest.ShowIndicator)", ".All("):
            self.assertNotIn(rule, adapter + offers, rule)

    def test_the_refresh_prunes_by_region_and_world(self):
        run = between(read(QUEST_INDICATORS), "private static void Run(GamePlayer player)", "\n    }\n")
        self.assertIn("LastSent.Prune(player, region, o => o is GameNPC npc && npc.ObjectState == "
                      "GameObject.eObjectState.Active,", run)


class HookNestingTests(unittest.TestCase):
    """The hooks that end their method are its last top-level statement (the others sit in a loop or an if by design)."""

    def test_the_level_and_class_and_add_quest_hooks(self):
        text = read(GAME_PLAYER)
        last_statement(self, between(text, "public override byte Level", "\n        }\n"),
                       "HearthDAoC.QuestIndicators.Refresh(this);", " " * 16)
        last_statement(self, between(text, "public virtual bool SetCharacterClass(int id)", "\n        }\n"),
                       "HearthDAoC.QuestIndicators.Refresh(this);", " " * 12)
        last_statement(self, between(text, "public bool AddQuest(AbstractQuest quest)", "\n        }\n"),
                       "HearthDAoC.QuestIndicators.Refresh(this);", " " * 12)

    def test_the_step_setter_and_the_data_quest_finish_and_abort_hooks(self):
        last_statement(self, between(read(ABSTRACT_QUEST), "public virtual int Step", "\n        }\n"),
                       "HearthDAoC.QuestIndicators.Refresh(m_questPlayer);", " " * 16)
        text = read(DATA_QUEST)
        last_statement(self, between(text, "public virtual bool FinishQuest(GameObject obj, bool checkCustomStep)",
                                     "\n\t\t}\n"), "HearthDAoC.QuestIndicators.Refresh(m_questPlayer);", "\t\t\t")
        last_statement(self, between(text, "public override void AbortQuest()", "\n\t\t}\n"),
                       "HearthDAoC.QuestIndicators.Refresh(m_questPlayer);", "\t\t\t")


class RefreshHookTests(unittest.TestCase):
    """Who asks for a refresh (spec 3.3)."""

    def test_the_level_setter(self):
        body = between(read(GAME_PLAYER), "public override byte Level", "\n        }\n")
        marked(self, body, "HearthDAoC.QuestIndicators.Refresh(this);")
        # After the level-up handling, on every change (up or down).
        self.assertLess(body.index("Out.SendLevelUpSound();"), body.index("QuestIndicators.Refresh(this);"))

    def test_the_class_change(self):
        body = between(read(GAME_PLAYER), "public virtual bool SetCharacterClass(int id)", "\n        }\n")
        marked(self, body, "HearthDAoC.QuestIndicators.Refresh(this);")
        self.assertLess(body.index("m_characterClass = cl;"), body.index("QuestIndicators.Refresh(this);"))

    def test_add_quest(self):
        body = between(read(GAME_PLAYER), "public bool AddQuest(AbstractQuest quest)", "\n        }\n")
        marked(self, body, "HearthDAoC.QuestIndicators.Refresh(this);")
        self.assertLess(body.index("QuestList.TryAdd(quest, index);"), body.index("QuestIndicators.Refresh(this);"))

    def test_the_step_setter_and_what_relies_on_it(self):
        text = read(ABSTRACT_QUEST)
        step = between(text, "public virtual int Step", "\n        }\n")
        marked(self, step, "HearthDAoC.QuestIndicators.Refresh(m_questPlayer);")
        # FinishQuest and AbortQuest go through the setter first, so they need no line of their own.
        finish = between(text, "public virtual void FinishQuest()", "\n        }\n")
        abort = between(text, "public virtual void AbortQuest()", "\n        }\n")
        self.assertRegex(finish, r"\{\s*Step = -2;")
        self.assertRegex(abort, r"\{\s*Step = -1;")

    def test_the_data_quest_overrides_that_skip_the_base(self):
        text = read(DATA_QUEST)
        step = between(text, "public override int Step", "\n\t\t}\n")
        marked(self, step, "HearthDAoC.QuestIndicators.Refresh(m_questPlayer);")
        finish = between(text, "public virtual bool FinishQuest(GameObject obj, bool checkCustomStep)", "\n\t\t}\n")
        marked(self, finish, "HearthDAoC.QuestIndicators.Refresh(m_questPlayer);")
        self.assertLess(finish.index("QuestIndicators.Refresh"), finish.rindex("return true;"))
        abort = between(text, "public override void AbortQuest()", "\n\t\t}\n")
        marked(self, abort, "HearthDAoC.QuestIndicators.Refresh(m_questPlayer);")

    def test_quests_finished_on_the_spot(self):
        # InteractComplete (CheckOfferQuest) and KillComplete (OnLivingIsDying) fill the finished list directly.
        text = read(DATA_QUEST)
        self.assertEqual(len(re.findall(
            r"player\.Out\.SendQuestListUpdate\(\);\n\t+HearthDAoC\.QuestIndicators\.Refresh\(player\); // HearthDAoC:",
            text)), 2)

    def test_the_daily_weekly_and_monthly_rollovers(self):
        # The rollover makes those quests available again: their givers' knots come back (owner keeps them, 2026-10-11).
        for path, kind in ((DAILY, "DailyQuest"), (WEEKLY, "WeeklyQuest"), (MONTHLY, "MonthlyQuest")):
            text = read(path)
            call = "HearthDAoC.QuestIndicators.Refresh(client.Player);"
            marked(self, text, call)
            self.assertLess(text.index(f"client.Player?.RemoveFinishedQuests(x => x is Quests.{kind});"),
                            text.index(call), path)

    def test_epic_done_and_reset(self):
        text = read(EPIC)
        for name in ("private void Done(", "private void Reset("):
            body = between(text, name, "\n    }\n")
            self.assertLess(body.index("target.Out.SendQuestListUpdate();"),
                            body.index("QuestIndicators.Refresh(target);"), name)

    def test_upstream_files_that_call_the_fork(self):
        # Every hook in upstream files, for upstream syncs (FORK.md).
        calls = {}
        for folder, _, names in os.walk(GAME_SERVER):
            if folder.startswith(FORK):
                continue
            for name in names:
                if name.endswith(".cs"):
                    count = len(re.findall(r"HearthDAoC\.QuestIndicators\.", read(os.path.join(folder, name))))
                    if count:
                        calls[name] = count
        self.assertEqual(calls, {
            "GameNPC.cs": 1,
            "PacketLib1124.cs": 1,
            "PacketLib173.cs": 1,
            "GamePlayer.cs": 3,
            "AbstractQuest.cs": 1,
            "DataQuest.cs": 5,
            "DailyQuestService.cs": 1,
            "WeeklyQuestService.cs": 1,
            "MonthlyQuestService.cs": 1,
        })


if __name__ == "__main__":
    unittest.main()

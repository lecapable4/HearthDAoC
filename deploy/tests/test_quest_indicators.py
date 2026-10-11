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


if __name__ == "__main__":
    unittest.main()

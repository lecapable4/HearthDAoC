"""The 25-quest journal (#112) on the paths that create a quest's record before GamePlayer.AddQuest decides (source
checks: these need a live player, client and database). QuestJournal's rules themselves are unit-tested
(Tests/UnitTests/UT_QuestJournal.cs).

- A scripted quest (bounties, faction emissaries, the ~80 scripted quests) is built by GameNPC.GiveQuest, whose
  constructor saves its DbQuest row at once. With a full journal that row stayed, the player was told nothing, and the
  login loaded it back into the journal past the cap. GiveQuest checks the journal first and says so, and removes the
  row of a quest AddQuest refuses (a duplicate).
- An abandoned data quest that was finished before (a repeatable) kept its step, so the next login put it back in the
  journal: its record keeps the finished count but goes back to step 0, as a finish leaves it.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GAME_SERVER = os.path.join(ROOT, "source", "server", "GameServer")


def read(*parts):
    with open(os.path.join(GAME_SERVER, *parts), encoding="utf-8-sig") as f:
        return f.read()


def method(text, signature, length=1500):
    start = text.index(signature)
    return text[start:start + length]


class ScriptedQuestTests(unittest.TestCase):
    def setUp(self):
        self.give = method(read("gameobjects", "GameNPC.cs"), "public bool GiveQuest(Type questType, GamePlayer player, int startStep)")

    def test_a_full_journal_refuses_before_the_quest_is_built(self):
        full = self.give.find("QuestJournal.IsFull(player.QuestList.Count)")
        built = self.give.find("Activator.CreateInstance(questType")
        self.assertGreater(full, 0)
        self.assertGreater(built, full)
        self.assertIn("DataQuestOffers.JournalFullText", self.give[full:built])
        self.assertIn("// HearthDAoC:", self.give[:built])

    def test_a_quest_add_quest_refuses_leaves_no_record(self):
        self.assertRegex(self.give, r"if \(newQuest != null\)\s*newQuest\.DeleteFromDatabase\(\);")


class AbandonedRepeatTests(unittest.TestCase):
    def test_an_abandoned_repeat_goes_back_to_step_0(self):
        abort = method(read("quests", "QuestsMgr", "DataQuest.cs"), "public override void AbortQuest()")
        self.assertRegex(abort, r"else\s*\{[^}]*m_charQuest\.Step = 0;\s*GameServer\.Database\.SaveObject\(m_charQuest\);")


if __name__ == "__main__":
    unittest.main()

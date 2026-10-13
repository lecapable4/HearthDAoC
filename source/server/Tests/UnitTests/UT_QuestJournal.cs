using System;
using DOL.Events;
using DOL.GS.Quests;
using NUnit.Framework;

namespace DOL.GS.Tests;

// HearthDAoC (#112): GamePlayer.AddQuest's journal rules. Upstream's "if (QuestList.Count > 25)" had no body, so it
// guarded the duplicate check after it: no journal limit, and no duplicate check below 26 quests. And that check
// compared C# types, which every data quest shares, so "always check" would have refused any data quest to a player
// already on another one.
[TestFixture]
public sealed class UT_QuestJournal
{
    private sealed class FakeDataQuest : DataQuest
    {
        private readonly int _id;
        public FakeDataQuest(int id) => _id = id;
        public override int ID => _id;
    }

    private abstract class Scripted : AbstractQuest
    {
        public override bool CheckQuestQualification(GamePlayer player) => true;
        public override void Notify(DOLEvent e, object sender, EventArgs args) { }
    }

    private sealed class ScriptedA : Scripted { }
    private sealed class ScriptedB : Scripted { }

    [Test]
    public void TheJournalHoldsTwentyFiveQuests()
    {
        Assert.Multiple(() =>
        {
            Assert.That(QuestJournal.IsFull(24), Is.False);
            Assert.That(QuestJournal.IsFull(25), Is.True);
            Assert.That(QuestJournal.IsFull(26), Is.True);
        });
    }

    [Test]
    public void DataQuestsAreTheSameQuestOnlyWithTheSameId()
    {
        Assert.Multiple(() =>
        {
            Assert.That(QuestJournal.Same(new FakeDataQuest(20171), new FakeDataQuest(20171)), Is.True);
            Assert.That(QuestJournal.Same(new FakeDataQuest(20171), new FakeDataQuest(20435)), Is.False);
        });
    }

    [Test]
    public void ScriptedQuestsAreTheSameQuestByTheirClass()
    {
        Assert.Multiple(() =>
        {
            Assert.That(QuestJournal.Same(new ScriptedA(), new ScriptedA()), Is.True);
            Assert.That(QuestJournal.Same(new ScriptedA(), new ScriptedB()), Is.False);
            Assert.That(QuestJournal.Same(new ScriptedA(), new FakeDataQuest(1)), Is.False);
        });
    }
}

using System.Collections.Generic;
using DOL.GS.Quests;
using NUnit.Framework;

namespace DOL.GS.Tests;

// HearthDAoC: a classic "choose your reward" step shows the item a player names (its delve window) and hands it over only
// when the player says "I'll take it" (owner 2026-10-12: the level-40 Guild of Shadows weapons were chosen blind). And an
// NPC's reply to a keyword can belong to one quest ("interested@20435"), for trainers who offer two quests with the same
// period keyword (owner 2026-10-12: level 43 moves from Magus Agyfen to each class's trainer, who offers 40 with
// "[interested]" too).
[TestFixture]
public sealed class UT_ClassicQuestsChoice
{
    private static readonly Dictionary<string, string> Choices = new()
    {
        ["Crackling Impaler"] = "cq_alb_crackling_impaler",
        ["Death's Touch"] = "cq_alb_death_s_touch",
        ["Death Dancer"] = "cq_alb_death_dancer",
        ["Spark of Midnight"] = "cq_alb_spark_of_midnight",
    };

    [Test]
    public void NamingAnItemShowsIt()
    {
        Assert.Multiple(() =>
        {
            Assert.That(ClassicQuests.ReadRewardWhisper(Choices, null, "Death Dancer"),
                Is.EqualTo((ClassicQuests.RewardWhisper.Show, "Death Dancer")));
            Assert.That(ClassicQuests.ReadRewardWhisper(Choices, null, "death dancer"),
                Is.EqualTo((ClassicQuests.RewardWhisper.Show, "Death Dancer")));
        });
    }

    [Test]
    public void NamingAnotherItemShowsThatOne()
    {
        Assert.That(ClassicQuests.ReadRewardWhisper(Choices, "Death Dancer", "Spark of Midnight"),
            Is.EqualTo((ClassicQuests.RewardWhisper.Show, "Spark of Midnight")));
    }

    [Test]
    public void TakingItHandsOverTheItemLastShown()
    {
        foreach (string words in new[] { "I'll take it", "i'll take it", "I’ll take it", "Ill take it", "I will take it", "I'll  take it" })
            Assert.That(ClassicQuests.ReadRewardWhisper(Choices, "Death Dancer", words),
                Is.EqualTo((ClassicQuests.RewardWhisper.Take, "Death Dancer")), words);
    }

    [Test]
    public void TakingItBeforeLookingAsksForANameFirst()
    {
        Assert.That(ClassicQuests.ReadRewardWhisper(Choices, null, "I'll take it"),
            Is.EqualTo((ClassicQuests.RewardWhisper.NothingShown, (string)null)));
    }

    [Test]
    public void AnItemShownForAnotherStepCannotBeTaken()
    {
        // The item a player last looked at belongs to one quest step; a name this step doesn't offer is nothing shown.
        Assert.That(ClassicQuests.ReadRewardWhisper(Choices, "Glitter", "I'll take it"),
            Is.EqualTo((ClassicQuests.RewardWhisper.NothingShown, (string)null)));
    }

    [Test]
    public void OtherWordsAreNotAboutTheReward()
    {
        foreach (string words in new[] { "interested", "take", "Death", "", null })
            Assert.That(ClassicQuests.ReadRewardWhisper(Choices, "Death Dancer", words),
                Is.EqualTo((ClassicQuests.RewardWhisper.None, (string)null)), words ?? "null");
    }

    private static readonly Dictionary<string, string> Edric = new(System.StringComparer.OrdinalIgnoreCase)
    {
        ["interested"] = "There is trouble in Snowdonia again.",
        ["interested@20435"] = "Many in Camelot have begun to speak of your missions for Sir Bors.",
        ["doubts"] = "I will say no more of it here.",
    };

    [Test]
    public void AQuestsOwnReplyWinsWhileThePlayerCanTakeIt()
    {
        Assert.Multiple(() =>
        {
            Assert.That(ClassicQuests.ChatReply(Edric, "interested", new[] { 20435 }),
                Is.EqualTo("Many in Camelot have begun to speak of your missions for Sir Bors."));
            Assert.That(ClassicQuests.ChatReply(Edric, "Interested", new[] { 21297, 20435 }),
                Is.EqualTo("Many in Camelot have begun to speak of your missions for Sir Bors."));
        });
    }

    [Test]
    public void ThePlainReplyAnswersOtherwise()
    {
        Assert.Multiple(() =>
        {
            Assert.That(ClassicQuests.ChatReply(Edric, "interested", new[] { 20171 }), Is.EqualTo("There is trouble in Snowdonia again."));
            Assert.That(ClassicQuests.ChatReply(Edric, "interested", new int[0]), Is.EqualTo("There is trouble in Snowdonia again."));
            Assert.That(ClassicQuests.ChatReply(Edric, "doubts", new[] { 20435 }), Is.EqualTo("I will say no more of it here."));
            Assert.That(ClassicQuests.ChatReply(Edric, "Snowdonia", new[] { 20435 }), Is.Null);
        });
    }

    [Test]
    public void TheExtraFilesQuestRepliesSurviveTheMerge()
    {
        var upstream = new ClassicQuests.Config();
        var extra = new ClassicQuests.Config
        {
            Chat = new() { ["Master Edric"] = new() { ["interested@20435"] = "Many in Camelot.", ["interested"] = "Trouble." } },
        };
        ClassicQuests.Config merged = ClassicQuests.Merge(upstream, extra);
        Assert.That(ClassicQuests.ChatReply(merged.Chat["master edric"], "INTERESTED", new[] { 20435 }), Is.EqualTo("Many in Camelot."));
    }
}

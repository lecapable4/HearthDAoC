using DOL.GS.Quests;
using NUnit.Framework;

namespace DOL.GS.Tests;

// HearthDAoC: a Whisper or WhisperFinish step whose AdvanceText holds a token the server replaces (<Player>, which
// BehaviourUtils.GetPersonalizedMessage makes the player's name) advances on that text as the player reads it, without
// case. Albion's "The Lost Stone" (20192-20195) asks for the player's name at Gavon Montgomery ("When he asks, tell him
// your name", the period guide); upstream's AdvanceText was the guide's "<your name>", which DataQuest compared as it
// is, so no whisper advanced the quest. A plain AdvanceText is still compared exactly, as upstream did.
[TestFixture]
public sealed class UT_DataQuestWhisper
{
    [TestCase("Lometur")]
    [TestCase("lometur")]
    [TestCase("LOMETUR")]
    public void TheNameTheStepAsksForAdvancesItWithoutCase(string whispered)
        => Assert.That(QuestWhispers.Advances("<Player>", "Lometur", whispered), Is.True);

    [TestCase("Thane")]
    [TestCase("Lometu")]
    [TestCase("Lometur ")]
    [TestCase("")]
    [TestCase(null)]
    public void AnotherWhisperDoesNotAdvanceIt(string whispered)
        => Assert.That(QuestWhispers.Advances("<Player>", "Lometur", whispered), Is.False);

    [Test]
    public void TheTokenStandsInsideTheTextToo()
        => Assert.That(QuestWhispers.Advances("I am <Player>", "I am Lometur", "i am lometur"), Is.True);

    [Test]
    public void TheTokenAsItIsStillMatchesAsUpstreamsComparisonDid()
        => Assert.That(QuestWhispers.Advances("<Player>", "Lometur", "<Player>"), Is.True);

    [TestCase("some time")]
    [TestCase("Lalida says hello")]
    public void APlainTextAdvancesOnItself(string advanceText)
        => Assert.That(QuestWhispers.Advances(advanceText, advanceText, advanceText), Is.True);

    [TestCase("Some time")]
    [TestCase("SOME TIME")]
    [TestCase("some time ")]
    public void APlainTextIsStillComparedExactly(string whispered)
        => Assert.That(QuestWhispers.Advances("some time", "some time", whispered), Is.False);

    // A token the server does not replace (upstream's "<your name>") reads as it is: it is plain text.
    [TestCase("<YOUR NAME>")]
    [TestCase("Lometur")]
    public void AnUnknownTokenIsPlainText(string whispered)
        => Assert.That(QuestWhispers.Advances("<your name>", "<your name>", whispered), Is.False);

    [Test]
    public void AnEmptyAdvanceTextNeedsAnEmptyWhisper()
    {
        Assert.Multiple(() =>
        {
            Assert.That(QuestWhispers.Advances("", "", "Lometur"), Is.False);
            Assert.That(QuestWhispers.Advances(null, null, "Lometur"), Is.False);
        });
    }
}

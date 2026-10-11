using System;
using System.Collections.Generic;
using DOL.GS.HearthDAoC;
using NUnit.Framework;

namespace DOL.GS.Tests;

// HearthDAoC: keeping quest markers current (spec docs/fork/specs/2026-10-11-quest-indicators-design.md, section 3.3):
// the wire value last sent per (player, NPC), one queued refresh per player however often it is asked, and a refresh
// that sends only what changed.
[TestFixture]
public sealed class UT_IndicatorSentStore
{
    // A refresh over the NPCs the client has, with these meanings; what it sends is added to sent.
    private static int Refresh(IndicatorSentStore store, object player, object[] known,
        Dictionary<object, eQuestIndicator> meaning, List<(object, eQuestIndicator)> sent) =>
        store.SendChanges(player, known, npc => (meaning[npc], (byte)QuestIndicators.Wire(meaning[npc])),
            (npc, m) => sent.Add((npc, m)));

    [Test]
    public void NothingSentReadsAsNothing()
    {
        var store = new IndicatorSentStore();
        Assert.That(store.Last(new object(), new object()), Is.EqualTo(0));
    }

    [Test]
    public void ZeroIsNotKept()
    {
        var store = new IndicatorSentStore();
        object player = new(), elaru = new();
        store.Record(player, elaru, 8);
        Assert.That(store.Count(player), Is.EqualTo(1));
        store.Record(player, elaru, 0);
        Assert.That(store.Count(player), Is.EqualTo(0));
        Assert.That(store.Last(player, elaru), Is.EqualTo(0));
    }

    [Test]
    public void OnlyChangedValuesAreSent()
    {
        var store = new IndicatorSentStore();
        object player = new(), elaru = new(), tage = new(), maggot = new();
        object[] known = { elaru, tage, maggot };
        var meaning = new Dictionary<object, eQuestIndicator>
        {
            [elaru] = eQuestIndicator.Available, [tage] = eQuestIndicator.None, [maggot] = eQuestIndicator.None,
        };
        var sent = new List<(object, eQuestIndicator)>();
        store.Record(player, elaru, 8); // Elaru's create packet carried the yellow knot.
        Assert.That(Refresh(store, player, known, meaning, sent), Is.EqualTo(0));

        // "Strange Beings" accepted: Elaru's knot goes, Tage's white knot comes.
        meaning[elaru] = eQuestIndicator.None;
        meaning[tage] = eQuestIndicator.Pending;
        Assert.That(Refresh(store, player, known, meaning, sent), Is.EqualTo(2));
        Assert.That(sent, Is.EqualTo(new[] { (elaru, eQuestIndicator.None), (tage, eQuestIndicator.Pending) }));
        Assert.That(store.Last(player, tage), Is.EqualTo(16));
        Assert.That(Refresh(store, player, known, meaning, sent), Is.EqualTo(0));
    }

    [Test]
    public void LoreAndLessonAreNothingSoNotSent()
    {
        var store = new IndicatorSentStore();
        object player = new(), trainer = new(), merchant = new();
        var meaning = new Dictionary<object, eQuestIndicator>
        {
            [trainer] = eQuestIndicator.Lore, [merchant] = eQuestIndicator.Lesson,
        };
        var sent = new List<(object, eQuestIndicator)>();
        Assert.That(Refresh(store, player, new[] { trainer, merchant }, meaning, sent), Is.EqualTo(0));
    }

    [Test]
    public void ARawValueSentIsPutRight()
    {
        // /indicator effect 1 drew the ring; the next refresh sends the real value (8, the yellow knot).
        var store = new IndicatorSentStore();
        object gm = new(), elaru = new();
        store.Record(gm, elaru, 1);
        var sent = new List<(object, eQuestIndicator)>();
        var meaning = new Dictionary<object, eQuestIndicator> { [elaru] = eQuestIndicator.Available };
        Assert.That(Refresh(store, gm, new[] { elaru }, meaning, sent), Is.EqualTo(1));
        Assert.That(store.Last(gm, elaru), Is.EqualTo(8));
    }

    [Test]
    public void ACreateThatChangesTheValueAsksARefreshThatSendsIt()
    {
        // Elaru lingered on the client with a yellow knot; she comes back into range with nothing for the player now.
        var store = new IndicatorSentStore();
        object player = new(), elaru = new();
        store.Record(player, elaru, 8);
        Assert.That(store.RecordCreate(player, elaru, 0), Is.True);
        Assert.That(store.Last(player, elaru), Is.EqualTo(IndicatorSentStore.Unknown));
        var sent = new List<(object, eQuestIndicator)>();
        var meaning = new Dictionary<object, eQuestIndicator> { [elaru] = eQuestIndicator.None };
        Assert.That(Refresh(store, player, new[] { elaru }, meaning, sent), Is.EqualTo(1));
        Assert.That(sent, Is.EqualTo(new[] { (elaru, eQuestIndicator.None) }));
        Assert.That(store.Last(player, elaru), Is.EqualTo(0));
    }

    [Test]
    public void ACreateWithTheSameValueAsksNothing()
    {
        var store = new IndicatorSentStore();
        object player = new(), tage = new(), guard = new();
        store.Record(player, tage, 16);
        Assert.That(store.RecordCreate(player, tage, 16), Is.False);
        Assert.That(store.RecordCreate(player, guard, 0), Is.False);
        Assert.That(store.Last(player, tage), Is.EqualTo(16));
    }

    [Test]
    public void AFirstCreateWithAMarkerIsSentAgainByTheRefresh()
    {
        var store = new IndicatorSentStore();
        object player = new(), elaru = new();
        Assert.That(store.RecordCreate(player, elaru, 8), Is.True);
        var sent = new List<(object, eQuestIndicator)>();
        var meaning = new Dictionary<object, eQuestIndicator> { [elaru] = eQuestIndicator.Available };
        Assert.That(Refresh(store, player, new[] { elaru }, meaning, sent), Is.EqualTo(1));
        Assert.That(store.Last(player, elaru), Is.EqualTo(8));
    }

    [Test]
    public void SeveralRequestsQueueOneRun()
    {
        var store = new IndicatorSentStore();
        object player = new();
        Assert.That(store.TryQueue(player), Is.True);
        Assert.That(store.TryQueue(player), Is.False);
        Assert.That(store.TryQueue(player), Is.False);
        Assert.That(store.Dequeue(player), Is.True);
        Assert.That(store.TryQueue(player), Is.True); // asked again during or after the run: the next tick's run
    }

    [Test]
    public void AnEmptyCacheSendsNothing()
    {
        var store = new IndicatorSentStore();
        object player = new();
        store.Record(player, new object(), 8);
        int count = store.SendChanges(player, Array.Empty<object>(), _ => (eQuestIndicator.Finish, (byte)2),
            (_, _) => Assert.Fail("sent with nothing on the client"));
        Assert.That(count, Is.EqualTo(0));
    }

    [Test]
    public void PlayersAreSeparate()
    {
        var store = new IndicatorSentStore();
        object one = new(), two = new(), elaru = new();
        store.Record(one, elaru, 8);
        Assert.That(store.Last(two, elaru), Is.EqualTo(0));
        Assert.That(store.TryQueue(one), Is.True);
        Assert.That(store.TryQueue(two), Is.True);
    }

    [Test]
    public void PruneDropsWhatIsGone()
    {
        var store = new IndicatorSentStore();
        object player = new(), elaru = new(), dead = new();
        store.Record(player, elaru, 8);
        store.Record(player, dead, 2);
        store.Prune(player, npc => ReferenceEquals(npc, dead));
        Assert.That(store.Last(player, elaru), Is.EqualTo(8));
        Assert.That(store.Last(player, dead), Is.EqualTo(0));
    }

    [Test]
    public void ForgetDropsThePlayerAndItsQueue()
    {
        var store = new IndicatorSentStore();
        object player = new(), elaru = new();
        store.Record(player, elaru, 2);
        Assert.That(store.TryQueue(player), Is.True);
        store.Forget(player);
        Assert.That(store.Last(player, elaru), Is.EqualTo(0));
        Assert.That(store.Dequeue(player), Is.False); // the posted run finds the player gone
    }
}

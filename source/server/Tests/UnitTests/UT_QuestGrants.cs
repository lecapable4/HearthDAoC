using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using DOL.GS.Quests;
using NUnit.Framework;

namespace DOL.GS.Tests;

// HearthDAoC (0.37 sync): upstream's ClassicQuests.GrantItems hands a step's granted item again whenever the player holds
// none in slots 7-249, once a minute, so that a quest token lost on the way can be had again. The sync made seven grants
// real rewards (Mystemas's Perfect Life Stone, Lilib's Pious Ring, Jytal's Ring of Spun Silk, Besje's Herbalist's
// Hauberk of Ivy, Scurceol's bracer, Hilde's Brack's Hammer), and a reward put in the account vault, sold or destroyed
// came back every minute. QuestGrants hands a real item once per character and quest, and remembers it in the
// character's custom parameters, so a restart keeps it; a quest token is left to upstream's re-issue.
[TestFixture]
public sealed class UT_QuestGrants
{
    private const string Owner = "character-1";
    private const int Bedfellows = 20975;
    private const string Stone = "cq_perfect_life_stone";

    /// <summary>The character custom parameters, as a set of (owner, entry).</summary>
    private sealed class Store : QuestGrants.IStore
    {
        public readonly HashSet<(string, string)> Rows = new();

        public bool Has(string owner, string entry)
        {
            lock (Rows)
                return Rows.Contains((owner, entry));
        }

        public void Add(string owner, string entry)
        {
            lock (Rows)
                Rows.Add((owner, entry));
        }
    }

    private Store _store;
    private int _handed;

    [SetUp]
    public void SetUp()
    {
        _store = new Store();
        _handed = 0;
    }

    private QuestGrants.Outcome Grant(bool held = false, bool room = true, bool token = false, string owner = Owner,
        int quest = Bedfellows, string item = Stone, QuestGrants.IStore store = null)
        => QuestGrants.Grant(store ?? _store, owner, quest, item, token, () => held, () =>
        {
            if (!room) return false;
            Interlocked.Increment(ref _handed);
            return true;
        });

    [Test]
    public void ARealItemIsHandedAndRemembered()
    {
        Assert.Multiple(() =>
        {
            Assert.That(Grant(), Is.EqualTo(QuestGrants.Outcome.Handed));
            Assert.That(_handed, Is.EqualTo(1));
            Assert.That(_store.Rows, Is.EquivalentTo(new[] { (Owner, "20975:cq_perfect_life_stone") }));
        });
    }

    // The finding (0.37 sync): the stone put in the account vault, sold or destroyed is no longer in slots 7-249.
    [Test]
    public void ARealItemPutAwayIsNotHandedAgain()
    {
        Grant();
        Assert.Multiple(() =>
        {
            Assert.That(Grant(), Is.EqualTo(QuestGrants.Outcome.AlreadyHanded));
            Assert.That(Grant(), Is.EqualTo(QuestGrants.Outcome.AlreadyHanded));
            Assert.That(_handed, Is.EqualTo(1));
        });
    }

    // QuestGrants keeps nothing of its own: what it was handed is in the store (the character's custom parameters in the
    // database), so a server restart, which starts with an empty memory, still knows.
    [Test]
    public void ARealItemHandedBeforeARestartIsNotHandedAfterIt()
    {
        Grant();
        var restarted = new Store();
        restarted.Rows.UnionWith(_store.Rows);
        Assert.Multiple(() =>
        {
            Assert.That(Grant(store: restarted), Is.EqualTo(QuestGrants.Outcome.AlreadyHanded));
            Assert.That(_handed, Is.EqualTo(1));
        });
    }

    // A copy the player carries on the step (a world upgraded from 0.35b, whose players already got the grant's copy)
    // counts as handed: put away, it does not come back either.
    [Test]
    public void ARealItemThePlayerHoldsCountsAsHanded()
    {
        Assert.Multiple(() =>
        {
            Assert.That(Grant(held: true), Is.EqualTo(QuestGrants.Outcome.Held));
            Assert.That(Grant(held: false), Is.EqualTo(QuestGrants.Outcome.AlreadyHanded));
            Assert.That(_handed, Is.EqualTo(0));
            Assert.That(_store.Rows, Is.EquivalentTo(new[] { (Owner, "20975:cq_perfect_life_stone") }));
        });
    }

    // Upstream's AddTemplate fails when the backpack has no room: nothing is remembered, and a later refresh tries again.
    [Test]
    public void ARealItemTheBackpackCannotTakeIsHandedLater()
    {
        Assert.Multiple(() =>
        {
            Assert.That(Grant(room: false), Is.EqualTo(QuestGrants.Outcome.NotHanded));
            Assert.That(_store.Rows, Is.Empty);
            Assert.That(Grant(), Is.EqualTo(QuestGrants.Outcome.Handed));
            Assert.That(_handed, Is.EqualTo(1));
        });
    }

    // A quest token (Item_Type 40, worth nothing) is upstream's to re-issue, as before: a lost key piece stalls no quest.
    [Test]
    public void ATokenIsLeftToUpstreamsReissue()
    {
        Assert.Multiple(() =>
        {
            Assert.That(Grant(token: true, item: "cq_second_key_piece"), Is.EqualTo(QuestGrants.Outcome.Upstream));
            Assert.That(Grant(token: true, item: "cq_second_key_piece"), Is.EqualTo(QuestGrants.Outcome.Upstream));
            Assert.That(_handed, Is.EqualTo(0));
            Assert.That(_store.Rows, Is.Empty);
        });
    }

    [Test]
    public void EachCharacterAndQuestHasItsOwnGrant()
    {
        Grant();
        Assert.Multiple(() =>
        {
            Assert.That(Grant(owner: "character-2"), Is.EqualTo(QuestGrants.Outcome.Handed));
            Assert.That(Grant(quest: 21021, item: "cq_pious_ring"), Is.EqualTo(QuestGrants.Outcome.Handed));
            Assert.That(Grant(quest: 21022, item: "cq_pious_ring"), Is.EqualTo(QuestGrants.Outcome.Handed));
            Assert.That(Grant(quest: 21264, item: "cq_ring_of_spun_silk"), Is.EqualTo(QuestGrants.Outcome.Handed));
            Assert.That(Grant(quest: 21264, item: "cq_herbalist_s_hauberk_of_ivy"), Is.EqualTo(QuestGrants.Outcome.Handed));
            Assert.That(_handed, Is.EqualTo(6));
        });
    }

    [Test]
    public void TheItemIdComparesWithoutCase()
    {
        Grant(item: "CQ_Perfect_Life_Stone ");
        Assert.That(Grant(item: "cq_perfect_life_stone"), Is.EqualTo(QuestGrants.Outcome.AlreadyHanded));
    }

    // The refresh runs on a timer, whose ticks can overlap when one runs long; the player's own actions run elsewhere.
    [Test]
    public void TwoRefreshesAtOnceHandItOnce()
    {
        var outcomes = new QuestGrants.Outcome[32];
        Parallel.For(0, outcomes.Length, i => outcomes[i] = QuestGrants.Grant(_store, Owner, Bedfellows, Stone, false, () => false, () =>
        {
            Thread.Sleep(5);
            Interlocked.Increment(ref _handed);
            return true;
        }));
        Assert.Multiple(() =>
        {
            Assert.That(_handed, Is.EqualTo(1));
            Assert.That(outcomes.Count(o => o == QuestGrants.Outcome.Handed), Is.EqualTo(1));
            Assert.That(outcomes.Count(o => o == QuestGrants.Outcome.AlreadyHanded), Is.EqualTo(outcomes.Length - 1));
        });
    }

    // Item_Type 40 is the backpack (eInventorySlot.FirstBackpack): carried, never worn. Price: what a merchant pays.
    [TestCase(40, 0, true)]     // upstream's carried-only copies: cq_second_key_piece, cq_diplomatic_documents
    [TestCase(40, 100, false)]  // "Zombie Problem"'s Cloudy Green Stone sells for 50 copper (mob_fixes.json)
    [TestCase(29, 0, false)]    // the Perfect Life Stone, a necklace
    [TestCase(10, 0, false)]    // Brack's Hammer, a hammer
    public void ATokenIsCarriedOnlyAndWorthNothing(int itemType, long price, bool token)
        => Assert.That(QuestGrants.IsToken(itemType, price), Is.EqualTo(token));

    [Test]
    public void TheEntryFitsTheCustomParameterColumns()
    {
        // CustomParam: KeyName VARCHAR(100), Value VARCHAR(255).
        Assert.Multiple(() =>
        {
            Assert.That(QuestGrants.Key.Length, Is.LessThanOrEqualTo(100));
            Assert.That(QuestGrants.Entry(21264, "cq_herbalist_s_hauberk_of_ivy"), Is.EqualTo("21264:cq_herbalist_s_hauberk_of_ivy"));
            Assert.That(QuestGrants.Entry(int.MaxValue, new string('x', 300)).Length, Is.LessThanOrEqualTo(255));
            Assert.That(QuestGrants.Entry(1, new string('x', 300)), Is.Not.EqualTo(QuestGrants.Entry(1, new string('x', 299))));
        });
    }
}

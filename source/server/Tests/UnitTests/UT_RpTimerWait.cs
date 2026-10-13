using System;
using System.Collections.Generic;
using System.Numerics;
using DOL.GS.HearthDAoC;
using NUnit.Framework;

namespace DOL.GS.Tests;

// HearthDAoC: gamebots come back worth realm points (spec docs/fork/specs/2026-10-13-rp-timer-waits-design.md,
// 10.1). A gamebot released after a death in RvR or a battleground waits at a safe spot and leaves when its time left
// is no more than its trip back to the fight, so it arrives just as it is worth realm points again. RpTimerWait and
// its types make every decision on plain values, with no server state, so these tests drive them directly; the game
// wiring (RpTimerWaitScript) and the controller part (RpTimerWaitController.cs) only feed them the bot's state.
[TestFixture]
public sealed class UT_RpTimerWait
{
    private static readonly Vector3 Bind = new(31_000, 30_000, 4_200);

    // A Released marker for death count 3, as hook 3 writes it for a bot released at its bind in the Albion frontier.
    private static RpWaitMarker Released() =>
        new(3, RpWaitPhase.Released, RpWaitCase.None, 1, Bind, 1, Bind, "albion-40-12-RvR", null, null, 0);

    // A slot holding this marker, written as hook 3 writes a bot's first marker: a swap against the null it read.
    private static RpWaitSlot SlotWith(RpWaitMarker marker)
    {
        var slot = new RpWaitSlot();
        Assert.That(slot.TrySwap(null, marker), Is.True);
        return slot;
    }

    [Test]
    public void ASwapAgainstTheMarkerReadSucceeds()
    {
        var slot = new RpWaitSlot();
        Assert.That(slot.Current, Is.Null);

        RpWaitMarker read = slot.Current;
        RpWaitMarker released = Released();
        Assert.That(slot.TrySwap(read, released), Is.True);
        Assert.That(slot.Current, Is.SameAs(released));

        read = slot.Current;
        RpWaitMarker waiting = read with { Phase = RpWaitPhase.Waiting, Case = RpWaitCase.Frontier, Started = 5_000 };
        Assert.That(slot.TrySwap(read, waiting), Is.True);
        Assert.That(slot.Current, Is.SameAs(waiting));
    }

    [Test]
    public void ASecondSwapFromAnOutOfDateReadFailsAndChangesNothing()
    {
        RpWaitMarker released = Released();
        RpWaitSlot slot = SlotWith(released);

        // Two writers read the same marker (the warband gate and the member's own hook); the first swap wins.
        RpWaitMarker read = slot.Current;
        RpWaitMarker waiting = read with { Phase = RpWaitPhase.Waiting, Case = RpWaitCase.Warband, Started = 5_000 };
        Assert.That(slot.TrySwap(read, waiting), Is.True);

        RpWaitMarker skipped = read with { Phase = RpWaitPhase.Left, Case = RpWaitCase.Frontier };
        Assert.That(slot.TrySwap(read, skipped), Is.False);
        Assert.That(slot.Current, Is.SameAs(waiting));
        Assert.That(released.Phase, Is.EqualTo(RpWaitPhase.Released));

        // A copy equal in every value to the marker now is still not the marker read: the swap compares references.
        Assert.That(slot.TrySwap(waiting with { }, skipped), Is.False);
        Assert.That(slot.Current, Is.SameAs(waiting));
    }

    [Test]
    public void ApplyReadsAgainAfterALostSwap()
    {
        RpWaitMarker released = Released();
        RpWaitSlot slot = SlotWith(released);
        RpWaitMarker started = released with
        {
            Phase = RpWaitPhase.Waiting, Case = RpWaitCase.Frontier, Started = 5_000,
        };
        var seen = new List<RpWaitMarker>();

        // The Dying handler's decision for the next death (3.7), while hook 2 starts the wait on the bot's own thread
        // between the handler's read and its swap.
        RpWaitChange change = slot.Apply(marker =>
        {
            seen.Add(marker);
            if (seen.Count == 1)
                Assert.That(slot.TrySwap(marker, started), Is.True);
            RpWaitMarker left = marker with { Phase = RpWaitPhase.Left };
            return marker.Phase == RpWaitPhase.Waiting
                ? new RpWaitChange(marker, left, RpWaitAction.Leave, RpWaitReason.Died)
                : new RpWaitChange(marker, left, RpWaitAction.None, RpWaitReason.None);
        });

        Assert.That(seen, Has.Count.EqualTo(2));
        Assert.That(seen[0], Is.SameAs(released));
        Assert.That(seen[1], Is.SameAs(started));
        Assert.That(change.Before, Is.SameAs(started));
        Assert.That(change.Action, Is.EqualTo(RpWaitAction.Leave));
        Assert.That(change.Reason, Is.EqualTo(RpWaitReason.Died));
        Assert.That(slot.Current, Is.SameAs(change.Next));
        Assert.That(slot.Current.Phase, Is.EqualTo(RpWaitPhase.Left));
    }

    [Test]
    public void ApplyStopsOnceItsDecisionKeepsTheMarker()
    {
        RpWaitMarker left = Released() with { Phase = RpWaitPhase.Left, Case = RpWaitCase.Frontier };
        RpWaitSlot slot = SlotWith(left);
        int calls = 0;

        // A player's invite (3.8) after the wait has ended: nothing to write.
        RpWaitChange change = slot.Apply(marker =>
        {
            calls++;
            return RpWaitChange.Keep(marker);
        });

        Assert.That(calls, Is.EqualTo(1));
        Assert.That(change.Changes, Is.False);
        Assert.That(change.Before, Is.SameAs(left));
        Assert.That(change.Next, Is.SameAs(left));
        Assert.That(change.Action, Is.EqualTo(RpWaitAction.None));
        Assert.That(slot.Current, Is.SameAs(left));
    }

    [Test]
    public void AChangeCopiesTheMarkerAndLeavesTheOldOneAsItWas()
    {
        RpWaitMarker waiting = Released() with
        {
            Phase = RpWaitPhase.Waiting, Case = RpWaitCase.Siege, EventKeepId = "rvr-keep-50", Started = 5_000,
        };
        RpWaitMarker left = waiting with { Phase = RpWaitPhase.Left };

        Assert.That(left, Is.Not.SameAs(waiting));
        Assert.That(waiting.Phase, Is.EqualTo(RpWaitPhase.Waiting));
        Assert.That(left.Phase, Is.EqualTo(RpWaitPhase.Left));
        Assert.That(left with { Phase = RpWaitPhase.Waiting }, Is.EqualTo(waiting));
        Assert.That(new RpWaitChange(waiting, left, RpWaitAction.Leave, RpWaitReason.Due).Changes, Is.True);

        RpWaitChange keep = RpWaitChange.Keep(waiting);
        Assert.That(keep.Changes, Is.False);
        Assert.That(keep.Next, Is.SameAs(keep.Before));
        Assert.That(keep.Action, Is.EqualTo(RpWaitAction.None));
        Assert.That(keep.Reason, Is.EqualTo(RpWaitReason.None));

        // A copy equal in every value is still another marker: a change is by reference, never by a record's ==.
        RpWaitMarker copy = waiting with { };
        Assert.That(copy == waiting, Is.True);
        Assert.That(new RpWaitChange(waiting, copy, RpWaitAction.None, RpWaitReason.None).Changes, Is.True);
    }

    // The realm point timer as the tests set it: a death at game time 1,000,000 and rp_worth_seconds 300 (2.1).
    private const long DeathTick = 1_000_000;
    private const int RpWorthSeconds = 300;

    // The central keep, as the spec measured it, the same in all four battlegrounds (3.1).
    private static readonly Vector2 CentralKeep = new(33_089, 38_271);

    // A game tick at 30 ticks a second (GameLoop.TickDuration); a brain may think up to half of one early (2.3).
    private const double TickAt30PerSecond = 1000.0 / 30;

    [Test]
    public void NoDeathOnRecordIsWorthAtOnce() =>
        Assert.That(RpTimerWait.WorthlessForMilliseconds(-1, 5_000_000, RpWorthSeconds), Is.EqualTo(0));

    [TestCase(0)]
    [TestCase(-5)]
    public void ZeroOrNegativeRpWorthSecondsIsWorthAtOnce(int rpWorthSeconds) =>
        Assert.That(RpTimerWait.WorthlessForMilliseconds(DeathTick, DeathTick, rpWorthSeconds), Is.EqualTo(0));

    // ARPR:86 pays once now - last >= the interval; until then the time left is the rest of it.
    [TestCase(0L, 300_000L)]
    [TestCase(299_999L, 1L)]
    [TestCase(300_000L, 0L)]
    [TestCase(400_000L, 0L)]
    public void TimeLeftAfterTheDeath(long sinceDeath, long expected) =>
        Assert.That(RpTimerWait.WorthlessForMilliseconds(DeathTick, DeathTick + sinceDeath, RpWorthSeconds),
            Is.EqualTo(expected));

    [Test]
    public void AClockBeforeTheDeathTickGivesTheWholeInterval() =>
        Assert.That(RpTimerWait.WorthlessForMilliseconds(DeathTick, DeathTick - 100_000, RpWorthSeconds),
            Is.EqualTo(300_000));

    // A released bot starts at a third of its health, below the 33% that slows its live speed (2.2).
    [Test]
    public void AHurtBotStillCountsItsBaseSpeed() =>
        Assert.That(RpTimerWait.BestSpeed(60, 191, 0), Is.EqualTo(191));

    // A singer starts its speed song only once it moves: a song of 140 counts while it stands.
    [Test]
    public void ItsOwnSpeedSongCounts() =>
        Assert.That(RpTimerWait.BestSpeed(60, 191, 140), Is.EqualTo(267.4).Within(1e-9));

    // Another bot's faster song already on it.
    [Test]
    public void AFasterLiveSpeedWins() =>
        Assert.That(RpTimerWait.BestSpeed(300, 191, 140), Is.EqualTo(300));

    [Test]
    public void TheTripIsTheStraightLineAtBestSpeedRoundedDown()
    {
        // Midgard's arrival point to its first contact point at 191 units/s (3.1): 42.83 s.
        Assert.That(RpTimerWait.TripMilliseconds(8_181, 191), Is.EqualTo(42_832));
        Assert.That(RpTimerWait.TripMilliseconds(190, 191), Is.EqualTo(994));
        Assert.That(RpTimerWait.TripMilliseconds(0, 191), Is.EqualTo(0));
    }

    [Test]
    public void NoSpeedMeansItNeverWaits()
    {
        Assert.That(RpTimerWait.TripMilliseconds(8_181, 0), Is.EqualTo(long.MaxValue));
        Assert.That(RpTimerWait.TripMilliseconds(8_181, -1), Is.EqualTo(long.MaxValue));

        // A bot waits while its time left is more than its trip: not even a death this moment is.
        long timeLeft = RpTimerWait.WorthlessForMilliseconds(DeathTick, DeathTick, RpWorthSeconds);
        Assert.That(timeLeft, Is.EqualTo(300_000));
        Assert.That(timeLeft > RpTimerWait.TripMilliseconds(8_181, 0), Is.False);

        // Its leave moment is the death itself, long past, and the arithmetic does not overflow.
        Assert.That(RpTimerWait.LeaveTick(DeathTick, RpWorthSeconds, long.MaxValue), Is.EqualTo(DeathTick));
    }

    // Each realm's BattlegroundBrackets.BotArrival: the first contact point lies 0.6 of the way to the central keep,
    // less the 900 a roamer patrols from its anchor and the 5,000 its threat scan reaches (3.1's table).
    [TestCase(36_428f, 51_260f, 2_147d, 35_893.5d, 49_180.8d)]
    [TestCase(53_150f, 26_093f, 8_181d, 46_156.9d, 30_338.2d)]
    [TestCase(19_714f, 19_085f, 8_133d, 24_364.9d, 25_756.6d)]
    public void FirstContactIsOnTheLineToTheCentralKeep(float arrivalX, float arrivalY, double fromArrival,
        double contactX, double contactY)
    {
        var arrival = new Vector2(arrivalX, arrivalY);
        Vector2 contact = RpTimerWait.FirstContactPoint(arrival, CentralKeep);

        Assert.That(Vector2.Distance(arrival, contact), Is.EqualTo(fromArrival).Within(1));
        Assert.That(contact.X, Is.EqualTo(contactX).Within(1));
        Assert.That(contact.Y, Is.EqualTo(contactY).Within(1));
        // On the line from the arrival to the keep: the two legs add up to the whole.
        Assert.That(Vector2.Distance(arrival, contact) + Vector2.Distance(contact, CentralKeep),
            Is.EqualTo(Vector2.Distance(arrival, CentralKeep)).Within(1));
    }

    [Test]
    public void AShortFieldGivesTheArrivalItself()
    {
        // |AC| = 9,000: 0.6 x 9,000 = 5,400, short of 900 + 5,000, so a patrol can see the arrival point itself.
        var arrival = new Vector2(10_000, 10_000);
        Assert.That(RpTimerWait.FirstContactPoint(arrival, new Vector2(10_000, 19_000)), Is.EqualTo(arrival));
        Assert.That(RpTimerWait.FirstContactPoint(arrival, arrival), Is.EqualTo(arrival));
    }

    [Test]
    public void LeaveTickIsWhenTimeLeftEqualsTheTrip()
    {
        long leave = RpTimerWait.LeaveTick(DeathTick, RpWorthSeconds, 42_832);
        Assert.That(leave, Is.EqualTo(DeathTick + 300_000 - 42_832));
        Assert.That(RpTimerWait.WorthlessForMilliseconds(DeathTick, leave, RpWorthSeconds), Is.EqualTo(42_832));
        Assert.That(RpTimerWait.WorthlessForMilliseconds(DeathTick, leave - 1, RpWorthSeconds), Is.EqualTo(42_833));

        // A trip longer than the interval: leave at once (the death tick, already past).
        Assert.That(RpTimerWait.LeaveTick(DeathTick, RpWorthSeconds, 400_000), Is.EqualTo(DeathTick));
    }

    [Test]
    public void TheWakeIsTheLeaveMomentPlusHalfATickRoundedUp()
    {
        Assert.That(RpTimerWait.ThinkWakeMilliseconds(DeathTick + 1_000, DeathTick, TickAt30PerSecond, 2_500),
            Is.EqualTo(1_017));
        // GameLoop.TickDuration is 0 in tests: no half tick.
        Assert.That(RpTimerWait.ThinkWakeMilliseconds(DeathTick + 1_000, DeathTick, 0, 2_500), Is.EqualTo(1_000));
    }

    [TestCase(100L)]
    [TestCase(-3_000L)]
    public void TheWakeIsAtLeast250Milliseconds(long leaveIn) =>
        Assert.That(RpTimerWait.ThinkWakeMilliseconds(DeathTick + leaveIn, DeathTick, TickAt30PerSecond, 2_500),
            Is.EqualTo(250));

    [Test]
    public void TheStandardIntervalWinsWhenItIsSooner() =>
        Assert.That(RpTimerWait.ThinkWakeMilliseconds(DeathTick + 5_000, DeathTick, TickAt30PerSecond, 2_500),
            Is.EqualTo(2_500));

    [Test]
    public void DistancesAreHorizontal()
    {
        Assert.That(RpTimerWait.Distance2D(new Vector3(0, 0, 0), new Vector3(3_000, 4_000, 0)), Is.EqualTo(5_000));
        Assert.That(RpTimerWait.Distance2D(new Vector3(0, 0, 0), new Vector3(3_000, 4_000, 2_500)), Is.EqualTo(5_000));
        Assert.That(RpTimerWait.Distance2D(Bind, new Vector3(Bind.X, Bind.Y, Bind.Z + 600)), Is.EqualTo(0));
    }

    [Test]
    public void TheRegionsAreTheWorlds()
    {
        for (int region = 0; region <= 1_000; region++)
        {
            ushort id = (ushort)region;
            Assert.That(RpTimerWait.IsBattlegroundRegion(id), Is.EqualTo(BattlegroundBrackets.IsBattlegroundRegion(id)),
                $"battleground region {id}");
            Assert.That(RpTimerWait.IsFrontierRegion(id), Is.EqualTo(id is 1 or 100 or 200), $"frontier region {id}");
        }
    }

    [Test]
    public void TheConstantsAreTheSpecs()
    {
        Assert.That(RpTimerWait.BindGate, Is.EqualTo(750));
        Assert.That(RpTimerWait.ArrivalGate, Is.EqualTo(2_500));
        Assert.That(RpTimerWait.SlotGate, Is.EqualTo(200));
        Assert.That(RpTimerWait.WalkBackBeyond, Is.EqualTo(200));
        Assert.That(RpTimerWait.SpotTolerance, Is.EqualTo(48));
        Assert.That(RpTimerWait.ContactShare, Is.EqualTo(0.6f));
        Assert.That(RpTimerWait.PatrolRadius, Is.EqualTo(900));
        Assert.That(RpTimerWait.ScanRadius, Is.EqualTo(5_000));
        Assert.That(RpTimerWait.WakeFloorMilliseconds, Is.EqualTo(250));
        Assert.That(RpTimerWait.FirstBattlegroundRegion, Is.EqualTo(250));
        Assert.That(RpTimerWait.LastBattlegroundRegion, Is.EqualTo(253));
        Assert.That(RpTimerWait.AlbionFrontier, Is.EqualTo(1));
        Assert.That(RpTimerWait.MidgardFrontier, Is.EqualTo(100));
        Assert.That(RpTimerWait.HiberniaFrontier, Is.EqualTo(200));
    }
}

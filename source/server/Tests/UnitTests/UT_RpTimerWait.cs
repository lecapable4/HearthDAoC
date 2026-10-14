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

    // The bot of Released() as hook 3 sees it: its RvR assignment id (realm, level band, epoch and goal, as AOA:519
    // builds it); its realm's arrival point in Thidranki (BattlegroundBrackets.BotArrival) and a slot 160 from it; a
    // warband slot by the Albion border keep and the warband's session id (GC:52-53).
    private const string RvrAssignment = "albion-40-12-RvR";
    private const ushort Thidranki = 252;
    private static readonly Vector3 AlbionArrival = new(36_428, 51_260, 3_952);
    private static readonly Vector3 AlbionArrivalSlot = new(36_588, 51_260, 3_952);
    private static readonly Vector3 BorderKeepSlot = new(29_640, 31_220, 4_310);
    private const string WarbandSession = "albion-7f3a-007";

    // A wait running for death count 3, started 20 s after the death: a frontier or siege wait at the bind in the
    // Albion frontier (a siege's with its event keep), a warband's at its slot by the border keep with its session, a
    // battleground's at its slot by its realm's arrival point in Thidranki.
    private static RpWaitMarker Waiting(RpWaitCase waitCase) => waitCase == RpWaitCase.Battleground
        ? new RpWaitMarker(3, RpWaitPhase.Waiting, RpWaitCase.Battleground, Thidranki, AlbionArrival, Thidranki,
            AlbionArrivalSlot, "albion-20-12-Battleground", null, null, DeathTick + 20_000)
        : Released() with
        {
            Phase = RpWaitPhase.Waiting,
            Case = waitCase,
            Spot = waitCase == RpWaitCase.Warband ? BorderKeepSlot : Bind,
            SessionId = waitCase == RpWaitCase.Warband ? WarbandSession : null,
            EventKeepId = waitCase == RpWaitCase.Siege ? "rvr-keep-50" : null,
            Started = DeathTick + 20_000,
        };

    // The marker of the bot's previous death (count 2), latched Left by the Dying handler at death 3 (3.7).
    private static RpWaitMarker PreviousDeathsMarker() =>
        Released() with { DeathCount = 2, Phase = RpWaitPhase.Left, Case = RpWaitCase.Frontier };

    // Hook 3 on the first controller turn after a release: alive, the release flag up, at its bind in the Albion
    // frontier with its RvR assignment, in no group, for death count 3. Each test sets what it is about.
    private static RpWaitChange ReleaseTurn(RpWaitMarker marker, bool enabled = true, int deathCount = 3,
        bool alive = true, bool returning = true, eAutonomousObjectiveKind goal = eAutonomousObjectiveKind.RvR) =>
        RpTimerWait.Note(enabled, marker, deathCount, alive, returning, goal, 1, Bind, RvrAssignment, inGroup: false,
            forceCommitted: false, musterOrder: false);

    // Hook 3 on a later turn of the same death (count 3): alive, the release flag down, at the marker's spot in its
    // region with its assignment id, in a group only for a warband marker, and the realm calling nothing.
    private static RpWaitChange LaterTurn(RpWaitMarker marker, bool enabled = true, ushort? region = null,
        string assignmentId = null, bool? inGroup = null, bool forceCommitted = false, bool musterOrder = false,
        bool returning = false)
    {
        eAutonomousObjectiveKind goal = marker.Case == RpWaitCase.Battleground
            ? eAutonomousObjectiveKind.Battleground
            : eAutonomousObjectiveKind.RvR;
        return RpTimerWait.Note(enabled, marker, 3, true, returning, goal, region ?? marker.Region, marker.Spot,
            assignmentId ?? marker.AssignmentId, inGroup ?? (marker.Case == RpWaitCase.Warband), forceCommitted,
            musterOrder);
    }

    // The change writes this Released marker over the one read (null: none), with no log line.
    private static void AssertNoted(RpWaitChange change, RpWaitMarker before, RpWaitMarker expected)
    {
        Assert.That(change.Before, Is.SameAs(before));
        Assert.That(change.Changes, Is.True);
        Assert.That(change.Next, Is.EqualTo(expected));
        Assert.That(change.Action, Is.EqualTo(RpWaitAction.None));
        Assert.That(change.Reason, Is.EqualTo(RpWaitReason.None));
    }

    // The change latches the marker read Left (a new marker, every other value the same) with this action and reason.
    private static void AssertLatched(RpWaitChange change, RpWaitMarker before, RpWaitAction action,
        RpWaitReason reason)
    {
        Assert.That(change.Before, Is.SameAs(before));
        Assert.That(change.Changes, Is.True);
        Assert.That(change.Next, Is.EqualTo(before with { Phase = RpWaitPhase.Left }));
        Assert.That(change.Action, Is.EqualTo(action));
        Assert.That(change.Reason, Is.EqualTo(reason));
    }

    // Nothing to write: the change keeps the marker read (the same reference, null included) and logs nothing.
    private static void AssertKept(RpWaitChange change, RpWaitMarker marker)
    {
        Assert.That(change.Before, Is.SameAs(marker));
        Assert.That(change.Next, Is.SameAs(marker));
        Assert.That(change.Action, Is.EqualTo(RpWaitAction.None));
        Assert.That(change.Reason, Is.EqualTo(RpWaitReason.None));
    }

    // 3.5: on an RvR or battleground goal, hook 3's first turn after a release writes Released for this death, with
    // where the bot stands as its release region and point (and its region and spot until a wait starts) and its
    // assignment id; no case, session, keep or start yet, and no log line.
    [TestCase(eAutonomousObjectiveKind.RvR)]
    [TestCase(eAutonomousObjectiveKind.Battleground)]
    public void AReleaseOnAnRvrOrBattlegroundGoalIsNoted(eAutonomousObjectiveKind goal)
    {
        string assignmentId = $"albion-20-12-{goal}";
        RpWaitChange change =
            RpTimerWait.Note(true, null, 3, true, true, goal, 1, Bind, assignmentId, false, false, false);

        AssertNoted(change, null, new RpWaitMarker(3, RpWaitPhase.Released, RpWaitCase.None, 1, Bind, 1, Bind,
            assignmentId, null, null, 0));
    }

    // 3.5: a PvE goal never waits; its release writes no marker, nor over the previous death's.
    [TestCase(eAutonomousObjectiveKind.SoloPve)]
    [TestCase(eAutonomousObjectiveKind.GroupPve)]
    public void AReleaseOnAPveGoalIsNotNoted(eAutonomousObjectiveKind goal)
    {
        AssertKept(ReleaseTurn(null, goal: goal), null);
        RpWaitMarker previous = PreviousDeathsMarker();
        AssertKept(ReleaseTurn(previous, goal: goal), previous);
    }

    // 2.4: only a release raises the flag (GB:1098). A resurrection clears it with no release (GB:1126); a dead bot is
    // not noted, flag or not (a death clears it, GB:947).
    [TestCase(true, false)]
    [TestCase(false, true)]
    public void NoNoteWhenResurrectedOrDead(bool alive, bool returning)
    {
        AssertKept(ReleaseTurn(null, alive: alive, returning: returning), null);
        RpWaitMarker previous = PreviousDeathsMarker();
        AssertKept(ReleaseTurn(previous, alive: alive, returning: returning), previous);
    }

    // 2.4: one marker per death. The flag can still be up on a later turn (the hand-over keeps it for a bot on a stable
    // master route, GB:1190-1192): a marker already Released or Left for this death is not written again, wherever the
    // bot stands now.
    [Test]
    public void AlreadyReleasedOrLeftForThisDeathIsUnchanged()
    {
        RpWaitMarker released = Released();
        AssertKept(RpTimerWait.Note(true, released, 3, true, true, eAutonomousObjectiveKind.RvR, 1,
            new Vector3(31_400, 30_300, 4_200), RvrAssignment, false, false, false), released);
        AssertKept(ReleaseTurn(released), released);

        RpWaitMarker left = released with { Phase = RpWaitPhase.Left, Case = RpWaitCase.Frontier };
        AssertKept(ReleaseTurn(left), left);
    }

    // 3.5: a new death's release writes over the previous death's marker (latched Left at the death, 3.7), with no
    // line.
    [Test]
    public void AReleaseAfterAnOlderDeathsMarkerIsNotedWithNoLine()
    {
        RpWaitMarker previous = PreviousDeathsMarker();
        AssertNoted(ReleaseTurn(previous), previous, Released());
    }

    // Section 6: with the switch off, hook 3 writes no marker.
    [Test]
    public void TheSwitchOffNotesNoRelease()
    {
        AssertKept(ReleaseTurn(null, enabled: false), null);
        RpWaitMarker previous = PreviousDeathsMarker();
        AssertKept(ReleaseTurn(previous, enabled: false), previous);
    }

    // Section 6: switched off, hook 3 ends a running wait on its next turn, before any other reason, and leaves a
    // Released marker as it is.
    [Test]
    public void TheSwitchOffEndsAWaitAndLeavesAReleasedMarker()
    {
        RpWaitMarker waiting = Waiting(RpWaitCase.Frontier);
        AssertLatched(LaterTurn(waiting, enabled: false), waiting, RpWaitAction.Leave, RpWaitReason.Off);
        AssertLatched(LaterTurn(waiting, enabled: false, region: 10, forceCommitted: true), waiting, RpWaitAction.Leave,
            RpWaitReason.Off);

        // A wait the warband gate started while the member's release flag was still up (GB:1190-1192) ends too.
        RpWaitMarker held = Waiting(RpWaitCase.Warband);
        AssertLatched(LaterTurn(held, enabled: false, returning: true), held, RpWaitAction.Leave, RpWaitReason.Off);

        RpWaitMarker released = Released();
        AssertKept(LaterTurn(released, enabled: false), released);
        AssertKept(ReleaseTurn(released, enabled: false), released);
    }

    // 2.4: a new goal, an ended task or battleground tour, or a solo siege force's release writes a new assignment id
    // (AOA:409-431, :434-445, :641; WBC:233-237); a bot in another region than its wait's (here Camelot, region 10)
    // has left it. Either ends the wait, whatever its case.
    [TestCase(RpWaitCase.Frontier)]
    [TestCase(RpWaitCase.Siege)]
    [TestCase(RpWaitCase.Warband)]
    [TestCase(RpWaitCase.Battleground)]
    public void AnotherAssignmentOrRegionEndsAWaitAtHook3(RpWaitCase waitCase)
    {
        RpWaitMarker waiting = Waiting(waitCase);
        AssertLatched(LaterTurn(waiting, assignmentId: "albion-40-13-RvR"), waiting, RpWaitAction.Leave,
            RpWaitReason.Changed);
        AssertLatched(LaterTurn(waiting, region: 10), waiting, RpWaitAction.Leave, RpWaitReason.Changed);
    }

    // 2.4: a warband marker on a bot no longer in a group ends; a solo's wait needs no group.
    [Test]
    public void AWarbandWaitWithNoGroupEnds()
    {
        RpWaitMarker held = Waiting(RpWaitCase.Warband);
        AssertLatched(LaterTurn(held, inGroup: false), held, RpWaitAction.Leave, RpWaitReason.Changed);
        AssertKept(LaterTurn(held, inGroup: true), held);

        RpWaitMarker solo = Waiting(RpWaitCase.Frontier);
        AssertKept(LaterTurn(solo, inGroup: false), solo);
    }

    // 3.5: the realm calls a frontier solo whose force joins any event (a muster, a battle draft, a relic event).
    [Test]
    public void AFrontierWaitEndsWhenItsForceIsCommitted()
    {
        RpWaitMarker waiting = Waiting(RpWaitCase.Frontier);
        AssertLatched(LaterTurn(waiting, forceCommitted: true), waiting, RpWaitAction.Leave, RpWaitReason.Called);
    }

    // 3.5: a siege member is called by a muster order for its force. Committed with no muster order, it waits on: a
    // move to another keep is hook 2's to end (3.3).
    [Test]
    public void ASiegeWaitEndsOnAMusterOrderOnly()
    {
        RpWaitMarker waiting = Waiting(RpWaitCase.Siege);
        AssertLatched(LaterTurn(waiting, musterOrder: true), waiting, RpWaitAction.Leave, RpWaitReason.Called);
        AssertKept(LaterTurn(waiting, forceCommitted: true), waiting);
    }

    // 3.5: a warband member is called by a muster order for its session, the force of a warband marker. Committed with
    // no muster order (a battle draft), it waits on: hook 2 converts it at its slot (3.4).
    [Test]
    public void AWarbandWaitEndsOnItsSessionsMusterOrderOnly()
    {
        RpWaitMarker held = Waiting(RpWaitCase.Warband);
        AssertLatched(LaterTurn(held, musterOrder: true), held, RpWaitAction.Leave, RpWaitReason.Called);
        AssertKept(LaterTurn(held, forceCommitted: true), held);
    }

    // 3.5: otherwise hook 3 leaves a wait alone; hooks 1-2 and the warband gate decide the rest.
    [TestCase(RpWaitCase.Frontier)]
    [TestCase(RpWaitCase.Siege)]
    [TestCase(RpWaitCase.Warband)]
    [TestCase(RpWaitCase.Battleground)]
    public void AWaitWithNothingChangedIsUnchanged(RpWaitCase waitCase)
    {
        RpWaitMarker waiting = Waiting(waitCase);
        AssertKept(LaterTurn(waiting), waiting);
    }

    // 3.7: the death count is raised (GB:953) before Dying fires, so the wait is now the previous death's: it ends with
    // its one leave, whatever its case. Died reads no switch: on or off, a death ends it.
    [TestCase(RpWaitCase.Frontier)]
    [TestCase(RpWaitCase.Siege)]
    [TestCase(RpWaitCase.Warband)]
    [TestCase(RpWaitCase.Battleground)]
    public void KilledWhileWaitingEndsTheWait(RpWaitCase waitCase)
    {
        RpWaitMarker waiting = Waiting(waitCase);
        AssertLatched(RpTimerWait.Died(waiting, 4), waiting, RpWaitAction.Leave, RpWaitReason.Died);
    }

    // 3.7: a Released marker of the previous death has no start, so it is latched with no line; a warband gate swap
    // that read it before the death then fails (7.2), so no start is logged.
    [Test]
    public void KilledWhileReleasedLatchesWithNoLineAndAStaleSwapFails()
    {
        RpWaitMarker released = Released();
        RpWaitSlot slot = SlotWith(released);
        RpWaitMarker gateRead = slot.Current;

        RpWaitChange died = slot.Apply(marker => RpTimerWait.Died(marker, 4));

        AssertLatched(died, released, RpWaitAction.None, RpWaitReason.None);
        Assert.That(slot.Current, Is.SameAs(died.Next));
        Assert.That(slot.TrySwap(gateRead, Waiting(RpWaitCase.Warband)), Is.False);
        Assert.That(slot.Current, Is.SameAs(died.Next));
        Assert.That(slot.Current.Phase, Is.EqualTo(RpWaitPhase.Left));
    }

    // 3.7: a marker already Left gets no second leave. Neither a marker for the death now (none can be: the count is
    // raised first) nor no marker at all is written.
    [Test]
    public void ALeftMarkerIsUnchangedByADeath()
    {
        RpWaitMarker left = Waiting(RpWaitCase.Frontier) with { Phase = RpWaitPhase.Left };
        AssertKept(RpTimerWait.Died(left, 4), left);

        RpWaitMarker waiting = Waiting(RpWaitCase.Frontier);
        AssertKept(RpTimerWait.Died(waiting, 3), waiting);
        AssertKept(RpTimerWait.Died(null, 4), null);
    }

    // 3.7, 2.4: killed while waiting, then resurrected where it fell (no release): its one leave came at the death,
    // hook 3 keeps the Left marker and ends nothing more, even switched off, and the bot fights on. Released instead,
    // it gets a new Released marker for the new death.
    [Test]
    public void AfterADeathAResurrectionIsIgnoredAndAReleaseIsNotedAgain()
    {
        RpWaitSlot slot = SlotWith(Waiting(RpWaitCase.Frontier));
        RpWaitChange died = slot.Apply(marker => RpTimerWait.Died(marker, 4));
        Assert.That(died.Action, Is.EqualTo(RpWaitAction.Leave));
        RpWaitMarker left = slot.Current;

        AssertKept(ReleaseTurn(left, deathCount: 4, returning: false), left);
        AssertKept(ReleaseTurn(left, enabled: false, deathCount: 4, returning: false), left);

        AssertNoted(ReleaseTurn(left, deathCount: 4), left, Released() with { DeathCount = 4 });
    }

    // 3.8: a player's invite (BotGroupInvite.cs:39-46) ends a wait with its leave and latches a release with no line,
    // so a bot the player drops within its timer never walks back to an old spot.
    [Test]
    public void JoiningAPlayersGroupEndsAWaitOrARelease()
    {
        RpWaitMarker waiting = Waiting(RpWaitCase.Frontier);
        AssertLatched(RpTimerWait.JoinedGroup(waiting, 3, true), waiting, RpWaitAction.Leave, RpWaitReason.PlayerGroup);

        RpWaitMarker released = Released();
        AssertLatched(RpTimerWait.JoinedGroup(released, 3, true), released, RpWaitAction.None, RpWaitReason.None);
    }

    // 3.8: a group led by a bot (a siege party's merge, SiegeParties.cs:59) changes nothing.
    [Test]
    public void JoiningABotsGroupChangesNothing()
    {
        foreach (RpWaitMarker marker in new[] { Waiting(RpWaitCase.Frontier), Waiting(RpWaitCase.Siege), Released() })
            AssertKept(RpTimerWait.JoinedGroup(marker, 3, false), marker);
    }

    // 3.8: only a marker for this death is latched: not an older death's (even one the Dying handler had not latched),
    // not a Left one, and no marker at all.
    [Test]
    public void AnOlderDeathsMarkerIsUnchangedByAJoin()
    {
        RpWaitMarker[] markers =
        {
            PreviousDeathsMarker(),
            Released() with { DeathCount = 2 },
            Waiting(RpWaitCase.Frontier) with { DeathCount = 2 },
            Waiting(RpWaitCase.Frontier) with { Phase = RpWaitPhase.Left },
        };
        foreach (RpWaitMarker marker in markers)
            AssertKept(RpTimerWait.JoinedGroup(marker, 3, true), marker);
        AssertKept(RpTimerWait.JoinedGroup(null, 3, true), null);
    }

    // A hook 1-2 turn 60 s after the death: 240 s left on the timer (2.1), against a trip of 42,832 ms (Midgard's 8,181
    // from its arrival point to first contact at 191 units/s, 3.1).
    private const long Now = DeathTick + 60_000;
    private const long TimeLeft = 240_000;
    private const long Trip = 42_832;

    // Albion's capital anchor in Camelot (AutonomousStuckWatchdog.CapitalFor), where an Albion bot with no bind of its
    // realm near its death releases (GB:1084-1089).
    private const ushort CamelotRegion = 10;
    private static readonly Vector3 Camelot = new(35_990, 30_298, 8_000);

    // The battleground bot of Waiting(Battleground), released for death count 3 outside the battleground (here in
    // Camelot) and back through the teleporter, which lands it on slot 0, its realm's arrival point
    // (TownTeleport.cs:139-142).
    private static RpWaitMarker ReleasedForTheBattleground() =>
        new(3, RpWaitPhase.Released, RpWaitCase.None, CamelotRegion, Camelot, CamelotRegion, Camelot,
            "albion-20-12-Battleground", null, null, 0);

    // What hook 1 or 2 sees on a turn where nothing has changed (3.1-3.4): a battleground bot at its slot in Thidranki
    // with its tour's assignment, its realm's arrival point and its slot; otherwise the bot of Released() in the Albion
    // frontier with its RvR assignment, at its bind (a warband member at its slot by the border keep), a siege's event
    // keep rvr-keep-50, and a trip target in its region (hook 2 gives a warband outside battle none). Each test changes
    // what it is about.
    private static RpWaitLook Look(RpWaitCase lookCase, Vector3? position = null, ushort? region = null,
        string assignmentId = null, string eventKeepId = null, bool relic = false, bool? hasTarget = null,
        ushort? targetRegion = null)
    {
        bool battleground = lookCase == RpWaitCase.Battleground;
        ushort here = region ?? (battleground ? Thidranki : (ushort)1);
        Vector3 standing = position ?? (battleground ? AlbionArrivalSlot
            : lookCase == RpWaitCase.Warband ? BorderKeepSlot : Bind);
        return new RpWaitLook(lookCase, here, standing,
            assignmentId ?? (battleground ? "albion-20-12-Battleground" : RvrAssignment),
            eventKeepId ?? (lookCase == RpWaitCase.Siege ? "rvr-keep-50" : null), relic,
            hasTarget ?? lookCase != RpWaitCase.Warband, targetRegion ?? here,
            battleground ? AlbionArrival : default, battleground ? AlbionArrivalSlot : default);
    }

    // Hooks 1-2's decision on that turn, for death count 3; each test sets what it is about.
    private static RpWaitDecision Turn(RpWaitMarker marker, RpWaitLook look, long timeLeft = TimeLeft, long trip = Trip,
        int deathCount = 3) =>
        RpTimerWait.Decide(marker, deathCount, look, timeLeft, trip, Now);

    // Ignore: the marker read is kept (the same reference, null included); no line, and the hook lets the bot go on.
    private static void AssertIgnored(RpWaitDecision decision, RpWaitMarker marker)
    {
        Assert.That(decision.Verdict, Is.EqualTo(RpWaitVerdict.Ignore));
        Assert.That(decision.Reason, Is.EqualTo(RpWaitReason.None));
        Assert.That(decision.Before, Is.SameAs(marker));
        Assert.That(decision.Next, Is.SameAs(marker));
        Assert.That(decision.Action, Is.EqualTo(RpWaitAction.None));
        Assert.That(decision.WalkBack, Is.False);
    }

    // A first look's Skip: the Released marker read is latched Left (a new marker) with the hook's case stored, with
    // this reason and its skip line (none for a bot already worth points).
    private static void AssertSkipped(RpWaitDecision decision, RpWaitMarker before, RpWaitCase hookCase,
        RpWaitReason reason, RpWaitAction action = RpWaitAction.Skip)
    {
        Assert.That(decision.Verdict, Is.EqualTo(RpWaitVerdict.Skip));
        Assert.That(decision.Reason, Is.EqualTo(reason));
        Assert.That(decision.Before, Is.SameAs(before));
        Assert.That(decision.Next, Is.Not.SameAs(before));
        Assert.That(decision.Next, Is.EqualTo(before with { Phase = RpWaitPhase.Left, Case = hookCase }));
        Assert.That(decision.Action, Is.EqualTo(action));
        Assert.That(decision.WalkBack, Is.False);
    }

    // A first look's Start: the Released marker read becomes this Waiting marker, with its start line.
    private static void AssertStarted(RpWaitDecision decision, RpWaitMarker before, RpWaitMarker expected,
        bool walkBack)
    {
        Assert.That(decision.Verdict, Is.EqualTo(RpWaitVerdict.Start));
        Assert.That(decision.Reason, Is.EqualTo(RpWaitReason.None));
        Assert.That(decision.Before, Is.SameAs(before));
        Assert.That(decision.Next, Is.EqualTo(expected));
        Assert.That(decision.Action, Is.EqualTo(RpWaitAction.Start));
        Assert.That(decision.WalkBack, Is.EqualTo(walkBack));
    }

    // A Hold: the wait goes on with the marker read (the same reference), no line; WalkBack when it must walk back.
    private static void AssertHeld(RpWaitDecision decision, RpWaitMarker marker, bool walkBack)
    {
        Assert.That(decision.Verdict, Is.EqualTo(RpWaitVerdict.Hold));
        Assert.That(decision.Reason, Is.EqualTo(RpWaitReason.None));
        Assert.That(decision.Before, Is.SameAs(marker));
        Assert.That(decision.Next, Is.SameAs(marker));
        Assert.That(decision.Action, Is.EqualTo(RpWaitAction.None));
        Assert.That(decision.WalkBack, Is.EqualTo(walkBack));
    }

    // A Leave: the Waiting marker read is latched Left (a new marker, every other value the same) with this reason and
    // its leave line.
    private static void AssertLeaves(RpWaitDecision decision, RpWaitMarker before, RpWaitReason reason)
    {
        Assert.That(decision.Verdict, Is.EqualTo(RpWaitVerdict.Leave));
        Assert.That(decision.Reason, Is.EqualTo(reason));
        Assert.That(decision.Before, Is.SameAs(before));
        Assert.That(decision.Next, Is.Not.SameAs(before));
        Assert.That(decision.Next, Is.EqualTo(before with { Phase = RpWaitPhase.Left }));
        Assert.That(decision.Action, Is.EqualTo(RpWaitAction.Leave));
        Assert.That(decision.WalkBack, Is.False);
    }

    // 2.4: hooks 1-2 act only on a marker for the death now. No marker (no release noted: a resurrection, a PvE goal,
    // the switch off) or a marker for an older death count is ignored, whatever the hook sees.
    [Test]
    public void NoMarkerOrAnOlderDeathsMarkerIsIgnored()
    {
        AssertIgnored(Turn(null, Look(RpWaitCase.Frontier)), null);
        AssertIgnored(Turn(null, Look(RpWaitCase.Battleground)), null);

        RpWaitMarker[] older =
        {
            PreviousDeathsMarker(),
            Released() with { DeathCount = 2 },
            Waiting(RpWaitCase.Frontier) with { DeathCount = 2 },
            Waiting(RpWaitCase.Siege) with { DeathCount = 2 },
        };
        foreach (RpWaitMarker marker in older)
        {
            AssertIgnored(Turn(marker, Look(RpWaitCase.Frontier)), marker);
            AssertIgnored(Turn(marker, Look(RpWaitCase.Siege), timeLeft: 0), marker);
        }
    }

    // 2.4: the latch. Once a first look has skipped or a wait has ended, nothing the bot sees later for that death
    // stops it again: a trip of 0 (it stands at its target), a new target, a target in another region, or a speed
    // song that shortens the trip.
    [Test]
    public void ALeftMarkerIsIgnoredWhateverChangesNext()
    {
        RpWaitMarker skipped = Released() with { Phase = RpWaitPhase.Left, Case = RpWaitCase.Frontier };
        RpWaitMarker ended = Waiting(RpWaitCase.Siege) with { Phase = RpWaitPhase.Left };
        foreach (RpWaitMarker left in new[] { skipped, ended })
        {
            AssertIgnored(Turn(left, Look(RpWaitCase.Frontier), trip: 0), left);
            AssertIgnored(Turn(left, Look(RpWaitCase.Siege, eventKeepId: "rvr-keep-51")), left);
            AssertIgnored(Turn(left, Look(RpWaitCase.Frontier, targetRegion: 100)), left);
            AssertIgnored(Turn(left, Look(RpWaitCase.Frontier), trip: 30_000), left);
        }

        RpWaitMarker battleground = Waiting(RpWaitCase.Battleground) with { Phase = RpWaitPhase.Left };
        AssertIgnored(Turn(battleground, Look(RpWaitCase.Battleground), trip: 0), battleground);
    }

    // 3.7: the Dying handler latches the marker Left for the old death count, so hooks 1-2 ignore it, with the count
    // now or the one a turn read before the death; and a Start decided from the Released marker before the death then
    // fails its swap, with no start line.
    [Test]
    public void AMarkerLatchedByADeathIsIgnored()
    {
        RpWaitSlot slot = SlotWith(Waiting(RpWaitCase.Frontier));
        slot.Apply(marker => RpTimerWait.Died(marker, 4));
        RpWaitMarker left = slot.Current;
        AssertIgnored(Turn(left, Look(RpWaitCase.Frontier), deathCount: 4), left);
        AssertIgnored(Turn(left, Look(RpWaitCase.Frontier), deathCount: 3), left);

        RpWaitMarker released = ReleasedForTheBattleground();
        RpWaitSlot battleground = SlotWith(released);
        RpWaitDecision start = Turn(released, Look(RpWaitCase.Battleground, position: AlbionArrival));
        Assert.That(start.Verdict, Is.EqualTo(RpWaitVerdict.Start));
        battleground.Apply(marker => RpTimerWait.Died(marker, 4));
        Assert.That(battleground.TrySwap(start.Before, start.Next), Is.False);

        RpWaitMarker latched = battleground.Current;
        Assert.That(latched.Phase, Is.EqualTo(RpWaitPhase.Left));
        AssertIgnored(Turn(latched, Look(RpWaitCase.Battleground, position: AlbionArrival), deathCount: 4), latched);
        AssertIgnored(Turn(latched, Look(RpWaitCase.Battleground, position: AlbionArrival), deathCount: 3), latched);
    }

    // Section 5: a relic carrier, a relic escort, interceptor or picker (a destination rvr-relic-carrier-) and a force
    // in a relic event (a battle with no keep plan, seen as Case Frontier with Relic) never wait, wherever they
    // stand: the relic comes before the region, the target, the gate and the trip.
    [Test]
    public void ARelicSkipsTheFirstLook()
    {
        RpWaitMarker released = Released();
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier, relic: true)), released, RpWaitCase.Frontier,
            RpWaitReason.Relic);
        AssertSkipped(Turn(released, Look(RpWaitCase.Siege, relic: true)), released, RpWaitCase.Siege,
            RpWaitReason.Relic);
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier, position: new Vector3(Bind.X + 3_000, Bind.Y, Bind.Z),
            region: 100, relic: true, hasTarget: false)), released, RpWaitCase.Frontier, RpWaitReason.Relic);
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier, relic: true), timeLeft: Trip), released,
            RpWaitCase.Frontier, RpWaitReason.Relic);
    }

    // 3.2, 3.3: a frontier or siege first look happens in the release region, with a target there. A bot released in
    // its capital (here Camelot) waits nowhere: not later in a frontier, nor at its capital bind with a target in a
    // frontier. A battleground bot has no such check: it always released outside and came in by the teleporter.
    [Test]
    public void AnotherRegionThanTheReleasePointOrTheTargetSkips()
    {
        RpWaitMarker inCamelot = Released() with
        {
            ReleaseRegion = CamelotRegion, ReleasePoint = Camelot, Region = CamelotRegion, Spot = Camelot,
        };
        AssertSkipped(Turn(inCamelot, Look(RpWaitCase.Frontier, region: 100)), inCamelot, RpWaitCase.Frontier,
            RpWaitReason.OtherRegion);
        AssertSkipped(Turn(inCamelot, Look(RpWaitCase.Siege, region: 100)), inCamelot, RpWaitCase.Siege,
            RpWaitReason.OtherRegion);
        AssertSkipped(Turn(inCamelot, Look(RpWaitCase.Frontier, position: Camelot, region: CamelotRegion,
            targetRegion: 100)), inCamelot, RpWaitCase.Frontier, RpWaitReason.OtherRegion);

        RpWaitMarker released = Released();
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier, targetRegion: 100)), released, RpWaitCase.Frontier,
            RpWaitReason.OtherRegion);
        AssertSkipped(Turn(released, Look(RpWaitCase.Siege, targetRegion: 200)), released, RpWaitCase.Siege,
            RpWaitReason.OtherRegion);

        RpWaitMarker battleground = ReleasedForTheBattleground();
        Assert.That(Turn(battleground, Look(RpWaitCase.Battleground, position: AlbionArrival)).Verdict,
            Is.EqualTo(RpWaitVerdict.Start));
    }

    // 3.1-3.3: no trip target (no destination nor death spot for a frontier solo, no event keep for a siege, no central
    // keep for a battleground): no wait. Before the gate: far from its bind with no target is no-target.
    [Test]
    public void NoTargetSkips()
    {
        RpWaitMarker released = Released();
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier, hasTarget: false)), released, RpWaitCase.Frontier,
            RpWaitReason.NoTarget);
        AssertSkipped(Turn(released, Look(RpWaitCase.Siege, hasTarget: false)), released, RpWaitCase.Siege,
            RpWaitReason.NoTarget);
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier, position: new Vector3(Bind.X, Bind.Y + 3_000, Bind.Z),
            hasTarget: false)), released, RpWaitCase.Frontier, RpWaitReason.NoTarget);

        RpWaitMarker battleground = ReleasedForTheBattleground();
        AssertSkipped(Turn(battleground, Look(RpWaitCase.Battleground, position: AlbionArrival, hasTarget: false)),
            battleground, RpWaitCase.Battleground, RpWaitReason.NoTarget);
    }

    // 3.1, 3.2: the first look's gate, horizontal (a bot 400 higher counts the same): within 2,500 of its realm's
    // arrival point in a battleground, within 750 of its release point (a bind) otherwise. Farther: moved-away.
    [TestCase(RpWaitCase.Battleground, 2_500f, true)]
    [TestCase(RpWaitCase.Battleground, 2_501f, false)]
    [TestCase(RpWaitCase.Frontier, 750f, true)]
    [TestCase(RpWaitCase.Frontier, 751f, false)]
    [TestCase(RpWaitCase.Siege, 750f, true)]
    [TestCase(RpWaitCase.Siege, 751f, false)]
    public void OutsideTheFirstLookGateSkips(RpWaitCase lookCase, float away, bool starts)
    {
        bool battleground = lookCase == RpWaitCase.Battleground;
        RpWaitMarker released = battleground ? ReleasedForTheBattleground() : Released();
        Vector3 gate = battleground ? AlbionArrival : Bind;
        var position = new Vector3(gate.X, gate.Y - away, gate.Z + 400);
        RpWaitDecision decision = Turn(released, Look(lookCase, position: position));

        if (starts)
        {
            Assert.That(decision.Verdict, Is.EqualTo(RpWaitVerdict.Start));
            Assert.That(decision.Next.Spot, Is.EqualTo(battleground ? AlbionArrivalSlot : Bind));
            Assert.That(decision.WalkBack, Is.True);
        }
        else
        {
            AssertSkipped(decision, released, lookCase, RpWaitReason.MovedAway);
        }
    }

    // 2.3: a bot whose time left is no more than its trip goes at once (equal is enough); 1 ms more and it waits. With
    // no speed (a trip of long.MaxValue) it never waits.
    [Test]
    public void TimeLeftWithinTheTripSkips()
    {
        RpWaitMarker released = Released();
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier), timeLeft: Trip), released, RpWaitCase.Frontier,
            RpWaitReason.Trip);
        AssertSkipped(Turn(released, Look(RpWaitCase.Siege), timeLeft: 10_000), released, RpWaitCase.Siege,
            RpWaitReason.Trip);
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier), trip: long.MaxValue), released, RpWaitCase.Frontier,
            RpWaitReason.Trip);
        Assert.That(Turn(released, Look(RpWaitCase.Frontier), timeLeft: Trip + 1).Verdict,
            Is.EqualTo(RpWaitVerdict.Start));

        RpWaitMarker battleground = ReleasedForTheBattleground();
        AssertSkipped(Turn(battleground, Look(RpWaitCase.Battleground, position: AlbionArrival), timeLeft: Trip),
            battleground, RpWaitCase.Battleground, RpWaitReason.Trip);
    }

    // 3.4, applied to the first look: a bot already worth points (time left 0) is latched Skip(Trip) with no line, as
    // the gate latches a Released member worth points, before any other check (a relic, another region, no target).
    [Test]
    public void AReleasedBotAlreadyWorthSkipsWithNoLine()
    {
        RpWaitMarker released = Released();
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier), timeLeft: 0), released, RpWaitCase.Frontier,
            RpWaitReason.Trip, RpWaitAction.None);
        AssertSkipped(Turn(released, Look(RpWaitCase.Siege, region: 100, relic: true, hasTarget: false), timeLeft: 0),
            released, RpWaitCase.Siege, RpWaitReason.Trip, RpWaitAction.None);

        RpWaitMarker battleground = ReleasedForTheBattleground();
        AssertSkipped(Turn(battleground, Look(RpWaitCase.Battleground, position: AlbionArrival), timeLeft: 0),
            battleground, RpWaitCase.Battleground, RpWaitReason.Trip, RpWaitAction.None);
    }

    // 3.1-3.3: a first look that passes every check starts a wait: a battleground bot at its slot, a frontier solo or a
    // siege member at its release point (its bind), with the region, the assignment id it has now (here a newer one
    // than at its release) and Started = now; it walks to its spot when more than 48 from it.
    [TestCase(RpWaitCase.Battleground, 0f, true)]
    [TestCase(RpWaitCase.Frontier, 0f, false)]
    [TestCase(RpWaitCase.Frontier, 300f, true)]
    [TestCase(RpWaitCase.Siege, 0f, false)]
    [TestCase(RpWaitCase.Siege, 300f, true)]
    public void TheFirstLookStartsAWait(RpWaitCase lookCase, float east, bool walkBack)
    {
        bool battleground = lookCase == RpWaitCase.Battleground;
        RpWaitMarker released = battleground ? ReleasedForTheBattleground() : Released();
        Vector3 landed = battleground ? AlbionArrival : Bind;
        string assignmentId = battleground ? "albion-20-13-Battleground" : "albion-40-13-RvR";
        RpWaitLook look = Look(lookCase, position: new Vector3(landed.X + east, landed.Y, landed.Z),
            assignmentId: assignmentId);

        AssertStarted(Turn(released, look), released, released with
        {
            Phase = RpWaitPhase.Waiting,
            Case = lookCase,
            Region = battleground ? Thidranki : (ushort)1,
            Spot = battleground ? AlbionArrivalSlot : Bind,
            AssignmentId = assignmentId,
            EventKeepId = lookCase == RpWaitCase.Siege ? "rvr-keep-50" : null,
            Started = Now,
        }, walkBack);
    }

    // 3.1: the teleporter lands a solo bot on slot 0, the arrival point itself, and slots 1 and 2 are 160 and 189
    // from it (AutonomousTownTeleporters.cs:148-152). A Start walks to its slot when more than 48 from it (IssuePath's
    // own arrival radius, WBC:5176-5180), not only past the 200 of a wait's later turns, where it holds.
    [TestCase(160f, true)]
    [TestCase(49f, true)]
    [TestCase(48f, false)]
    [TestCase(20f, false)]
    public void TheFirstLookWalksToABattlegroundSlotOnly160Away(float away, bool walkBack)
    {
        RpWaitMarker released = ReleasedForTheBattleground();
        RpWaitLook look = Look(RpWaitCase.Battleground,
            position: new Vector3(AlbionArrivalSlot.X - away, AlbionArrivalSlot.Y, AlbionArrivalSlot.Z));

        RpWaitDecision start = Turn(released, look);
        Assert.That(start.Verdict, Is.EqualTo(RpWaitVerdict.Start));
        Assert.That(start.Next.Spot, Is.EqualTo(AlbionArrivalSlot));
        Assert.That(start.WalkBack, Is.EqualTo(walkBack));

        AssertHeld(Turn(start.Next, look), start.Next, false);
    }

    // 3.3: a siege wait stores the event keep (_rvrDestination.Id) its trip goes to, so a later draft to another keep
    // ends it; a frontier or battleground wait stores none, even from a look that carries one. No session id: a bot
    // released alone.
    [Test]
    public void ASiegeStartStoresTheEventKeep()
    {
        RpWaitMarker released = Released();
        RpWaitDecision siege = Turn(released, Look(RpWaitCase.Siege, eventKeepId: "rvr-keep-51"));
        Assert.That(siege.Verdict, Is.EqualTo(RpWaitVerdict.Start));
        Assert.That(siege.Next.Case, Is.EqualTo(RpWaitCase.Siege));
        Assert.That(siege.Next.EventKeepId, Is.EqualTo("rvr-keep-51"));
        Assert.That(siege.Next.SessionId, Is.Null);

        RpWaitDecision frontier = Turn(released, Look(RpWaitCase.Frontier, eventKeepId: "rvr-keep-51"));
        Assert.That(frontier.Verdict, Is.EqualTo(RpWaitVerdict.Start));
        Assert.That(frontier.Next.EventKeepId, Is.Null);

        RpWaitMarker inBattleground = ReleasedForTheBattleground();
        RpWaitDecision battleground = Turn(inBattleground,
            Look(RpWaitCase.Battleground, position: AlbionArrival, eventKeepId: "rvr-keep-51"));
        Assert.That(battleground.Verdict, Is.EqualTo(RpWaitVerdict.Start));
        Assert.That(battleground.Next.EventKeepId, Is.Null);
    }

    // 3.4: a warband regrouping outside a siege battle is the warband gate's (hook 4). Hook 2 neither starts
    // nor skips its first look, whatever it sees: worth already, within the trip, far from its bind, a relic (the
    // gate's own relic check says go).
    [Test]
    public void AReleasedWarbandMemberOutsideBattleIsTheGates()
    {
        RpWaitMarker released = Released();
        AssertIgnored(Turn(released, Look(RpWaitCase.Warband)), released);
        AssertIgnored(Turn(released, Look(RpWaitCase.Warband), timeLeft: 0), released);
        AssertIgnored(Turn(released, Look(RpWaitCase.Warband), timeLeft: Trip), released);
        AssertIgnored(Turn(released, Look(RpWaitCase.Warband, position: new Vector3(Bind.X, Bind.Y + 3_000, Bind.Z))),
            released);
        AssertIgnored(Turn(released, Look(RpWaitCase.Warband, relic: true)), released);
    }

    // 2.3: a wait holds while time left is more than the trip and leaves (due) on the first turn where it is no more,
    // each bot at its own moment, a battleground bot too; with no speed it leaves at once.
    [TestCase(RpWaitCase.Frontier)]
    [TestCase(RpWaitCase.Siege)]
    [TestCase(RpWaitCase.Battleground)]
    public void AWaitHoldsUntilTimeLeftEqualsTheTrip(RpWaitCase waitCase)
    {
        RpWaitMarker waiting = Waiting(waitCase);
        AssertHeld(Turn(waiting, Look(waitCase), timeLeft: Trip + 1), waiting, false);
        AssertLeaves(Turn(waiting, Look(waitCase), timeLeft: Trip), waiting, RpWaitReason.Due);
        AssertLeaves(Turn(waiting, Look(waitCase), timeLeft: 0), waiting, RpWaitReason.Due);
        AssertLeaves(Turn(waiting, Look(waitCase), trip: long.MaxValue), waiting, RpWaitReason.Due);
    }

    // Section 4, 2.4: a fight never ends a wait. Afterwards a bot more than 200 from its spot holds and walks back,
    // from any distance; within 200 it holds where it is. Horizontal: 400 higher counts the same.
    [TestCase(200f, false)]
    [TestCase(201f, true)]
    [TestCase(3_000f, true)]
    public void AWaitFarFromItsSpotHoldsAndWalksBack(float away, bool walkBack)
    {
        foreach (RpWaitCase waitCase in new[] { RpWaitCase.Frontier, RpWaitCase.Siege, RpWaitCase.Battleground })
        {
            RpWaitMarker waiting = Waiting(waitCase);
            var position = new Vector3(waiting.Spot.X, waiting.Spot.Y + away, waiting.Spot.Z + 400);
            AssertHeld(Turn(waiting, Look(waitCase, position: position)), waiting, walkBack);
        }
    }

    // 2.4: a new assignment id or another region than the wait's ends it (hook 3 usually first), whatever the case and
    // before anything else the hook sees (a warband's look included: it is the gate's only while nothing changed).
    [TestCase(RpWaitCase.Frontier)]
    [TestCase(RpWaitCase.Siege)]
    [TestCase(RpWaitCase.Warband)]
    [TestCase(RpWaitCase.Battleground)]
    public void AnotherAssignmentOrRegionEndsAWait(RpWaitCase waitCase)
    {
        RpWaitMarker waiting = Waiting(waitCase);
        AssertLeaves(Turn(waiting, Look(waitCase, assignmentId: "albion-40-13-RvR")), waiting, RpWaitReason.Changed);
        AssertLeaves(Turn(waiting, Look(waitCase, region: CamelotRegion)), waiting, RpWaitReason.Changed);
        AssertLeaves(Turn(waiting, Look(waitCase, assignmentId: "albion-40-13-RvR", relic: true, hasTarget: false),
            timeLeft: 0), waiting, RpWaitReason.Changed);
    }

    // 2.4, 3.4: a case change seen by hooks 1-2 ends a wait (changed): a frontier wait that sees a siege (hook 3 has
    // usually ended a drafted solo's wait first, as called), a siege wait that sees the frontier, a frontier or siege
    // wait that sees a warband outside battle, and a warband wait that hook 2 sees as neither a warband nor a siege.
    [TestCase(RpWaitCase.Frontier, RpWaitCase.Siege)]
    [TestCase(RpWaitCase.Siege, RpWaitCase.Frontier)]
    [TestCase(RpWaitCase.Frontier, RpWaitCase.Warband)]
    [TestCase(RpWaitCase.Siege, RpWaitCase.Warband)]
    [TestCase(RpWaitCase.Warband, RpWaitCase.Frontier)]
    public void ACaseChangeEndsAWait(RpWaitCase waitCase, RpWaitCase lookCase)
    {
        RpWaitMarker waiting = Waiting(waitCase);
        AssertLeaves(Turn(waiting, Look(lookCase, position: waiting.Spot)), waiting, RpWaitReason.Changed);
    }

    // Section 5: a relic ends a wait, before the case, the target and the time: a relic carrier or escort
    // (the wait's own case with Relic), a siege member caught in a relic event (a battle with no keep plan: Case
    // Frontier with Relic), and a waiting warband member that hook 2 reaches as a relic carrier (WBC:459).
    [Test]
    public void ARelicEndsAWait()
    {
        foreach (RpWaitCase waitCase in new[] { RpWaitCase.Frontier, RpWaitCase.Siege })
        {
            RpWaitMarker waiting = Waiting(waitCase);
            AssertLeaves(Turn(waiting, Look(waitCase, relic: true)), waiting, RpWaitReason.Relic);
            AssertLeaves(Turn(waiting, Look(waitCase, relic: true, hasTarget: false), timeLeft: 0), waiting,
                RpWaitReason.Relic);
        }

        RpWaitMarker siege = Waiting(RpWaitCase.Siege);
        AssertLeaves(Turn(siege, Look(RpWaitCase.Frontier, relic: true)), siege, RpWaitReason.Relic);

        RpWaitMarker held = Waiting(RpWaitCase.Warband);
        AssertLeaves(Turn(held, Look(RpWaitCase.Warband, relic: true)), held, RpWaitReason.Relic);
    }

    // 2.4: a target gone or in another region ends a wait (no-target, other-region), before its time: a target in
    // another region with time left within the trip logs other-region, not due. A drafted warband member too.
    [TestCase(RpWaitCase.Frontier, RpWaitCase.Frontier)]
    [TestCase(RpWaitCase.Siege, RpWaitCase.Siege)]
    [TestCase(RpWaitCase.Battleground, RpWaitCase.Battleground)]
    [TestCase(RpWaitCase.Warband, RpWaitCase.Siege)]
    public void AGoneTargetEndsAWait(RpWaitCase waitCase, RpWaitCase lookCase)
    {
        RpWaitMarker waiting = Waiting(waitCase);
        AssertLeaves(Turn(waiting, Look(lookCase, position: waiting.Spot, hasTarget: false)), waiting,
            RpWaitReason.NoTarget);
        AssertLeaves(Turn(waiting, Look(lookCase, position: waiting.Spot, targetRegion: 100)), waiting,
            RpWaitReason.OtherRegion);
        AssertLeaves(Turn(waiting, Look(lookCase, position: waiting.Spot, targetRegion: 100), timeLeft: 0), waiting,
            RpWaitReason.OtherRegion);
    }

    // 3.3: the draft can move a defence force to another defence (ELD:294-307) with no muster order for hook 3 to see:
    // hook 2 sees another event keep than the stored one and ends the wait as called, in its region or another (the
    // keep comes before the region). A warband member converted at its slot likewise. The same keep holds.
    [Test]
    public void ASiegeWaitEndsWhenTheDraftMovesItToAnotherKeep()
    {
        RpWaitMarker siege = Waiting(RpWaitCase.Siege);
        AssertLeaves(Turn(siege, Look(RpWaitCase.Siege, eventKeepId: "rvr-keep-51")), siege, RpWaitReason.Called);
        AssertLeaves(Turn(siege, Look(RpWaitCase.Siege, region: 100, eventKeepId: "rvr-keep-51")), siege,
            RpWaitReason.Called);
        AssertHeld(Turn(siege, Look(RpWaitCase.Siege)), siege, false);

        RpWaitMarker converted =
            Turn(Waiting(RpWaitCase.Warband), Look(RpWaitCase.Siege, position: BorderKeepSlot)).Next;
        Assert.That(converted.Case, Is.EqualTo(RpWaitCase.Siege));
        AssertLeaves(Turn(converted, Look(RpWaitCase.Siege, position: BorderKeepSlot, eventKeepId: "rvr-keep-51")),
            converted, RpWaitReason.Called);
        AssertHeld(Turn(converted, Look(RpWaitCase.Siege, position: BorderKeepSlot)), converted, false);
    }

    // 3.4 "Drafted mid-wait": a held warband drafted into a battle reaches hook 2 as a siege. Within 200 of its slot in
    // the stored region it stays Waiting, as a siege member at its slot: the event keep stored; the session id, region,
    // spot and assignment id kept; Started now. One Convert (leave reason=battle, then start case=siege), no walk.
    [Test]
    public void AWaitingWarbandDraftedIntoABattleConvertsAtItsSlot()
    {
        RpWaitMarker held = Waiting(RpWaitCase.Warband);
        foreach (float away in new[] { 0f, 120f, 200f })
        {
            RpWaitLook look = Look(RpWaitCase.Siege,
                position: new Vector3(BorderKeepSlot.X, BorderKeepSlot.Y - away, BorderKeepSlot.Z),
                eventKeepId: "rvr-keep-51");

            RpWaitDecision decision = Turn(held, look);

            Assert.That(decision.Verdict, Is.EqualTo(RpWaitVerdict.Convert));
            Assert.That(decision.Reason, Is.EqualTo(RpWaitReason.Battle));
            Assert.That(decision.Action, Is.EqualTo(RpWaitAction.Convert));
            Assert.That(decision.Before, Is.SameAs(held));
            Assert.That(decision.Next, Is.EqualTo(held with
            {
                Case = RpWaitCase.Siege, EventKeepId = "rvr-keep-51", Started = Now,
            }));
            Assert.That(decision.Next.Phase, Is.EqualTo(RpWaitPhase.Waiting));
            Assert.That(decision.Next.Spot, Is.EqualTo(BorderKeepSlot));
            Assert.That(decision.Next.SessionId, Is.EqualTo(WarbandSession));
            Assert.That(decision.WalkBack, Is.False);
        }
    }

    // 3.4: farther than 200 from its slot, or with time left no more than its trip to the event keep, a drafted
    // member's wait ends (moved-away, due; the slot comes first) and it goes in as today.
    [Test]
    public void ADraftedWarbandMemberAwayFromItsSlotOrDueLeaves()
    {
        RpWaitMarker held = Waiting(RpWaitCase.Warband);
        var away300 = new Vector3(BorderKeepSlot.X, BorderKeepSlot.Y - 300, BorderKeepSlot.Z);
        var away201 = new Vector3(BorderKeepSlot.X, BorderKeepSlot.Y - 201, BorderKeepSlot.Z);
        AssertLeaves(Turn(held, Look(RpWaitCase.Siege, position: away300)), held, RpWaitReason.MovedAway);
        AssertLeaves(Turn(held, Look(RpWaitCase.Siege, position: away201)), held, RpWaitReason.MovedAway);
        AssertLeaves(Turn(held, Look(RpWaitCase.Siege, position: BorderKeepSlot), timeLeft: Trip), held,
            RpWaitReason.Due);
        AssertLeaves(Turn(held, Look(RpWaitCase.Siege, position: away300), timeLeft: Trip), held,
            RpWaitReason.MovedAway);
    }

    // 3.4: a waiting warband member that hook 2 sees as a warband outside battle is the gate's: Ignore, whatever
    // its time, distance or target (the regroup walks it back to its slot; the gate opens it).
    [Test]
    public void AWaitingWarbandMarkerOutsideBattleIsTheGates()
    {
        RpWaitMarker held = Waiting(RpWaitCase.Warband);
        AssertIgnored(Turn(held, Look(RpWaitCase.Warband)), held);
        AssertIgnored(Turn(held, Look(RpWaitCase.Warband), timeLeft: 0), held);
        AssertIgnored(Turn(held, Look(RpWaitCase.Warband), timeLeft: Trip), held);
        AssertIgnored(Turn(held, Look(RpWaitCase.Warband,
            position: new Vector3(BorderKeepSlot.X, BorderKeepSlot.Y - 3_000, BorderKeepSlot.Z))), held);
    }

    // 3.4: a member whose marker is still Released when its warband is drafted (the gate had not held it yet) gets the
    // plain siege first look at its bind: at a slot 3,000 from it, moved-away; at its bind, a siege wait there.
    [Test]
    public void AReleasedWarbandMemberInABattleFarFromItsBindSkips()
    {
        RpWaitMarker released = Released();
        AssertSkipped(Turn(released, Look(RpWaitCase.Siege, position: new Vector3(Bind.X, Bind.Y + 3_000, Bind.Z))),
            released, RpWaitCase.Siege, RpWaitReason.MovedAway);

        RpWaitDecision atBind = Turn(released, Look(RpWaitCase.Siege));
        Assert.That(atBind.Verdict, Is.EqualTo(RpWaitVerdict.Start));
        Assert.That(atBind.Next.Spot, Is.EqualTo(Bind));
        Assert.That(atBind.Next.SessionId, Is.Null);
    }

    // 2.4: only a new release after a new death resets the latch. A wait for death 3 starts and ends; hook 3 writes
    // Released for death 4 over its Left marker, and the next first look starts a new wait.
    [Test]
    public void ANewDeathAndReleaseStartsAgain()
    {
        RpWaitSlot slot = SlotWith(Released());
        RpWaitDecision start = Turn(slot.Current, Look(RpWaitCase.Frontier));
        Assert.That(start.Verdict, Is.EqualTo(RpWaitVerdict.Start));
        Assert.That(slot.TrySwap(start.Before, start.Next), Is.True);
        RpWaitDecision due = Turn(slot.Current, Look(RpWaitCase.Frontier), timeLeft: Trip);
        Assert.That(due.Verdict, Is.EqualTo(RpWaitVerdict.Leave));
        Assert.That(slot.TrySwap(due.Before, due.Next), Is.True);
        AssertIgnored(Turn(slot.Current, Look(RpWaitCase.Frontier)), slot.Current);

        slot.Apply(marker => RpTimerWait.Died(marker, 4));
        RpWaitChange noted = ReleaseTurn(slot.Current, deathCount: 4);
        Assert.That(slot.TrySwap(noted.Before, noted.Next), Is.True);

        RpWaitDecision again = Turn(slot.Current, Look(RpWaitCase.Frontier), deathCount: 4);
        AssertStarted(again, slot.Current, Waiting(RpWaitCase.Frontier) with { DeathCount = 4, Started = Now }, false);
    }

    // 2.4, 3.1-3.4: trips are measured from the spot of the wait: for a Released bot its battleground slot (hook 1) or
    // its release point, a bind (hook 2), wherever it stands; for a waiting bot its stored spot (its slot, its bind, or
    // its warband slot, after a Convert too), whatever the hook sees now. A Left marker gives its stored spot.
    [Test]
    public void TheSpotIsTheSlotTheBindOrTheStoredSpot()
    {
        Assert.That(RpTimerWait.WaitSpot(ReleasedForTheBattleground(),
            Look(RpWaitCase.Battleground, position: AlbionArrival)), Is.EqualTo(AlbionArrivalSlot));
        Assert.That(RpTimerWait.WaitSpot(Released(),
            Look(RpWaitCase.Frontier, position: new Vector3(Bind.X + 300, Bind.Y, Bind.Z))), Is.EqualTo(Bind));
        Assert.That(RpTimerWait.WaitSpot(Released(), Look(RpWaitCase.Siege)), Is.EqualTo(Bind));

        var elsewhere = new Vector3(20_000, 20_000, 3_000);
        foreach (RpWaitCase waitCase in new[]
            { RpWaitCase.Frontier, RpWaitCase.Siege, RpWaitCase.Warband, RpWaitCase.Battleground })
        {
            RpWaitMarker waiting = Waiting(waitCase);
            Assert.That(RpTimerWait.WaitSpot(waiting, Look(RpWaitCase.Battleground, position: elsewhere)),
                Is.EqualTo(waiting.Spot));
            Assert.That(RpTimerWait.WaitSpot(waiting, Look(RpWaitCase.Siege, position: elsewhere)),
                Is.EqualTo(waiting.Spot));
        }

        RpWaitMarker converted =
            Waiting(RpWaitCase.Warband) with { Case = RpWaitCase.Siege, EventKeepId = "rvr-keep-50" };
        Assert.That(RpTimerWait.WaitSpot(converted, Look(RpWaitCase.Siege)), Is.EqualTo(BorderKeepSlot));
        RpWaitMarker left = Waiting(RpWaitCase.Warband) with { Phase = RpWaitPhase.Left };
        Assert.That(RpTimerWait.WaitSpot(left, Look(RpWaitCase.Siege)), Is.EqualTo(BorderKeepSlot));
    }

    // The warband of 3.4, regrouping by the Albion border keep in the Albion frontier (region 1): its rendezvous (the
    // session's Rendezvous), two more members' slots beside BorderKeepSlot, and where a member died this death, 9,550
    // from the rendezvous: a march of 50,000 ms at 191 units/s (300 lower: the march is horizontal).
    private static readonly Vector3 Rendezvous = new(29_500, 31_000, 4_310);
    private static readonly Vector3 SecondSlot = new(29_360, 31_220, 4_310);
    private static readonly Vector3 ThirdSlot = new(29_500, 30_740, 4_310);
    private static readonly Vector3 DeathSpot = new(29_500, 40_550, 4_010);
    private const long March = 50_000;

    // The gate's go with no march: it opens on the members (it writes), or it writes nothing (the switch off, a
    // session that is not RvR, a committed force).
    private static readonly RpWarbandGate OpensWithNoMarch = new(false, true, 0, 0);
    private static readonly RpWarbandGate GoesWithNoWrites = new(false, false, 0, 0);

    // A warband member released for death 3 to Albion's capital, Camelot (an invader's or a far death's release),
    // with its RvR assignment.
    private static RpWaitMarker ReleasedInCamelot() =>
        new(3, RpWaitPhase.Released, RpWaitCase.None, CamelotRegion, Camelot, CamelotRegion, Camelot, RvrAssignment,
            null, null, 0);

    // A member as the gate sees it on a pass (3.4): its marker and time left, its death count 3 and its death record
    // for it at DeathSpot in the Albion frontier, standing in the Albion frontier at its slot (BorderKeepSlot) with
    // its RvR assignment and a best speed of 191. Each test sets what it is about (the record with a with).
    private static RpWarbandMember Member(RpWaitMarker marker, long timeLeft, int deathCount = 3, ushort region = 1,
        Vector3? slot = null, string assignmentId = RvrAssignment, double bestSpeed = 191) =>
        new(marker, deathCount, timeLeft, new RpDeathRecord(deathCount, 1, DeathSpot, DeathTick, DeathTick), region,
            slot ?? BorderKeepSlot, assignmentId, bestSpeed);

    // Hook 4's gate on a pass of that warband's regroup: the switch on, an RvR session, no committed force and no
    // relic carrier, unless a test says otherwise.
    private static RpWarbandGate Gate(RpWarbandMember[] members, bool enabled = true,
        eAutonomousObjectiveKind kind = eAutonomousObjectiveKind.RvR, bool forceCommitted = false,
        bool relicCarrier = false) =>
        RpTimerWait.WarbandWaits(enabled, kind, forceCommitted, relicCarrier, 1, Rendezvous, members);

    // The gate's writes on that pass, at Now, for the warband's session.
    private static RpWaitChange[] Marks(RpWarbandGate gate, RpWarbandMember[] members) =>
        RpTimerWait.WarbandMarks(gate, 1, members, WarbandSession, Now);

    // The holding gate turns the member's Released marker Waiting (a new marker): case warband, the rendezvous region,
    // its slot as the spot, its assignment id now, the session id, no event keep, Started now; its start line.
    private static void AssertTurnedWaiting(RpWaitChange change, RpWarbandMember member)
    {
        Assert.That(change.Before, Is.SameAs(member.Marker));
        Assert.That(change.Changes, Is.True);
        Assert.That(change.Next, Is.EqualTo(member.Marker with
        {
            Phase = RpWaitPhase.Waiting,
            Case = RpWaitCase.Warband,
            Region = 1,
            Spot = member.Slot,
            AssignmentId = member.AssignmentId,
            SessionId = WarbandSession,
            EventKeepId = null,
            Started = Now,
        }));
        Assert.That(change.Action, Is.EqualTo(RpWaitAction.Start));
        Assert.That(change.Reason, Is.EqualTo(RpWaitReason.None));
    }

    // The gate writes nothing: one change per member, in member order, each keeping its marker (null included).
    private static void AssertNothingWritten(RpWaitChange[] changes, RpWarbandMember[] members)
    {
        Assert.That(changes, Has.Length.EqualTo(members.Length));
        for (int i = 0; i < members.Length; i++)
            AssertKept(changes[i], members[i].Marker);
    }

    // 3.4: the warband leaves together once its member released for this death with the most time left can make the
    // march from the rendezvous to where it died: the gate holds while that time left is more than the march, and an
    // equal one goes. The holder is the member with the most time left wherever it stands in the party, and the march
    // is to its own death, not another member's (19,100 away: 100,000 ms).
    [TestCase(240_000L, true)]
    [TestCase(50_001L, true)]
    [TestCase(50_000L, false)]
    [TestCase(49_999L, false)]
    public void TheGateWaitsWhileTheMostTimeLeftExceedsTheMarch(long holderTimeLeft, bool waits)
    {
        var farDeath = new RpDeathRecord(3, 1, new Vector3(Rendezvous.X, Rendezvous.Y + 19_100, 4_000), DeathTick,
            DeathTick);
        RpWarbandMember[] members =
        {
            Member(Released(), 30_000, slot: SecondSlot) with { Death = farDeath },
            Member(Released(), holderTimeLeft),
        };

        Assert.That(Gate(members), Is.EqualTo(new RpWarbandGate(waits, true, March, holderTimeLeft)));
    }

    // 3.4, choice 18: a member resurrected in the field has no marker for its current death (none, or its previous
    // death's, latched Left), so it doesn't hold the gate, however much time it has left; a released member does.
    [Test]
    public void AResurrectedMemberDoesNotHoldTheGate()
    {
        RpWarbandMember resurrected = Member(PreviousDeathsMarker(), 280_000);
        RpWarbandMember neverReleased = Member(null, 290_000, slot: SecondSlot);
        RpWarbandMember released = Member(Released(), 40_000, slot: ThirdSlot);

        Assert.That(Gate(new[] { resurrected, neverReleased, released }),
            Is.EqualTo(new RpWarbandGate(false, true, March, 40_000)));
        Assert.That(Gate(new[] { resurrected, neverReleased }), Is.EqualTo(OpensWithNoMarch));
    }

    // Section 5, 3.4: never with a relic carrier in the party: go, even with members' time left above the march, and
    // the gate opens on them as on any opening.
    [Test]
    public void ARelicCarrierMeansGo()
    {
        RpWarbandMember[] members =
        {
            Member(Waiting(RpWaitCase.Warband), 200_000),
            Member(Released(), 240_000, slot: SecondSlot),
        };

        RpWarbandGate gate = Gate(members, relicCarrier: true);

        Assert.That(gate, Is.EqualTo(OpensWithNoMarch));
        RpWaitChange[] changes = Marks(gate, members);
        AssertLatched(changes[0], members[0].Marker, RpWaitAction.Leave, RpWaitReason.Due);
        AssertLatched(changes[1], members[1].Marker, RpWaitAction.Skip, RpWaitReason.Trip);
    }

    // 3.4: only RvR sessions wait. A Group PvE party reaches the same regroup completion after a wipe, and a monster
    // kill restarts the timer too: go, and nothing written, even with members' time left above the march. Any other
    // kind but RvR likewise.
    [Test]
    public void AGroupPveSessionMeansGoAndWritesNothing()
    {
        RpWarbandMember[] members =
        {
            Member(Waiting(RpWaitCase.Warband), 200_000),
            Member(Released(), 240_000, slot: SecondSlot),
        };
        var notRvr = new[]
        {
            eAutonomousObjectiveKind.GroupPve, eAutonomousObjectiveKind.SoloPve, eAutonomousObjectiveKind.Battleground,
        };
        foreach (eAutonomousObjectiveKind kind in notRvr)
        {
            RpWarbandGate gate = Gate(members, kind: kind);

            Assert.That(gate, Is.EqualTo(GoesWithNoWrites), kind.ToString());
            AssertNothingWritten(Marks(gate, members), members);
        }
    }

    // 3.4: every member released for this death is worth points already (time left 0): nobody holds the gate, and its
    // opening latches them, a Released one with no line, a Waiting one with its leave.
    [Test]
    public void AllWorthMeansGo()
    {
        RpWarbandMember[] members =
        {
            Member(Waiting(RpWaitCase.Warband), 0),
            Member(Released(), 0, slot: SecondSlot),
        };

        RpWarbandGate gate = Gate(members);

        Assert.That(gate, Is.EqualTo(OpensWithNoMarch));
        RpWaitChange[] changes = Marks(gate, members);
        AssertLatched(changes[0], members[0].Marker, RpWaitAction.Leave, RpWaitReason.Due);
        AssertLatched(changes[1], members[1].Marker, RpWaitAction.None, RpWaitReason.None);
    }

    // Section 6: with the switch off the gate says go at once and writes nothing, even with members Waiting or Released
    // for this death above the march: a Waiting member stays Waiting until its own hook 3 ends it (off), never the gate
    // (due), and a Released one stays Released, as hook 3 leaves it.
    [Test]
    public void TheSwitchOffMeansGoAndWritesNothing()
    {
        RpWarbandMember[] members =
        {
            Member(Waiting(RpWaitCase.Warband), 200_000),
            Member(Released(), 240_000, slot: SecondSlot),
        };

        RpWarbandGate gate = Gate(members, enabled: false);

        Assert.That(gate, Is.EqualTo(GoesWithNoWrites));
        AssertNothingWritten(Marks(gate, members), members);
        AssertLatched(LaterTurn(members[0].Marker, enabled: false), members[0].Marker, RpWaitAction.Leave,
            RpWaitReason.Off);
        AssertKept(LaterTurn(members[1].Marker, enabled: false), members[1].Marker);
    }

    // 3.4 "Not in a muster": a warband enrolled in an event whose battle has not started still regroups, but its force
    // is committed (IsForceCommitted): go, and nothing written, even with members' time left above the march. A member
    // already Waiting is its hook 3's to end (called, at the muster order).
    [Test]
    public void ACommittedForceMeansGoAndWritesNothing()
    {
        RpWarbandMember[] members =
        {
            Member(Waiting(RpWaitCase.Warband), 200_000),
            Member(Released(), 240_000, slot: SecondSlot),
        };

        RpWarbandGate gate = Gate(members, forceCommitted: true);

        Assert.That(gate, Is.EqualTo(GoesWithNoWrites));
        AssertNothingWritten(Marks(gate, members), members);
        AssertLatched(LaterTurn(members[0].Marker, musterOrder: true), members[0].Marker, RpWaitAction.Leave,
            RpWaitReason.Called);
    }

    // 3.4: the march needs where the holder died for this death, in the rendezvous region. No death record, one for
    // its previous death, or a death in another region (an invader's, in the Midgard frontier): go, even though
    // another member's record would give a march (the holder decides).
    [Test]
    public void NoMatchingDeathRecordOrADeathInAnotherRegionMeansGo()
    {
        RpWarbandMember other = Member(Released(), 100_000, slot: SecondSlot);
        RpWarbandMember holder = Member(Released(), 240_000);
        Assert.That(Gate(new[] { other, holder }), Is.EqualTo(new RpWarbandGate(true, true, March, 240_000)));

        RpDeathRecord[] unusable =
        {
            null,
            new RpDeathRecord(2, 1, DeathSpot, DeathTick - 400_000, DeathTick - 400_000),
            new RpDeathRecord(3, 100, DeathSpot, DeathTick, DeathTick),
        };
        foreach (RpDeathRecord death in unusable)
            Assert.That(Gate(new[] { other, holder with { Death = death } }), Is.EqualTo(OpensWithNoMarch));
    }

    // 3.4: the march is at the best speed of the fastest member, holding the gate or not: a singer's own
    // song of 140 (267.4 units/s) makes the 9,550 a march of 35,714 ms, so 40,000 left holds; a resurrected member at
    // 300 (another's song on it) makes it 31,833.
    [Test]
    public void TheMarchIsAtTheFastestMembersBestSpeed()
    {
        RpWarbandMember holder = Member(Released(), 40_000);
        Assert.That(Gate(new[] { holder }), Is.EqualTo(new RpWarbandGate(false, true, March, 40_000)));

        RpWarbandMember singer = Member(Released(), 20_000, slot: SecondSlot, bestSpeed: 267.4);
        Assert.That(Gate(new[] { holder, singer }), Is.EqualTo(new RpWarbandGate(true, true, 35_714, 40_000)));

        RpWarbandMember resurrected = Member(null, 250_000, slot: ThirdSlot, bestSpeed: 300);
        Assert.That(Gate(new[] { holder, singer, resurrected }),
            Is.EqualTo(new RpWarbandGate(true, true, 31_833, 40_000)));
    }

    // 3.4, 2.4: a member whose wait for death 3 the gate ended is killed again, 5,730 from the rendezvous (a march of
    // 30,000 ms), and released: hook 3 writes Released for death 4 over its Left marker, which holds the gate again
    // and turns Waiting at its slot.
    [Test]
    public void AMemberKilledAgainAndReleasedMakesItWaitAgain()
    {
        RpWaitSlot slot = SlotWith(Waiting(RpWaitCase.Warband));
        RpWarbandMember[] members = { Member(slot.Current, March) };
        RpWarbandGate opened = Gate(members);
        Assert.That(opened.Waits, Is.False);
        RpWaitChange due = Marks(opened, members)[0];
        Assert.That(due.Reason, Is.EqualTo(RpWaitReason.Due));
        Assert.That(slot.TrySwap(due.Before, due.Next), Is.True);

        Assert.That(slot.Apply(marker => RpTimerWait.Died(marker, 4)).Changes, Is.False);
        RpWaitChange noted = ReleaseTurn(slot.Current, deathCount: 4);
        Assert.That(slot.TrySwap(noted.Before, noted.Next), Is.True);

        var secondDeath = new RpDeathRecord(4, 1, new Vector3(Rendezvous.X + 5_730, Rendezvous.Y, 4_200),
            DeathTick + 400_000, DeathTick + 400_000);
        members = new[] { Member(slot.Current, 280_000, deathCount: 4) with { Death = secondDeath } };
        RpWarbandGate holding = Gate(members);

        Assert.That(holding, Is.EqualTo(new RpWarbandGate(true, true, 30_000, 280_000)));
        RpWaitChange[] changes = Marks(holding, members);
        AssertTurnedWaiting(changes[0], members[0]);
        Assert.That(changes[0].Next.DeathCount, Is.EqualTo(4));
        Assert.That(slot.TrySwap(changes[0].Before, changes[0].Next), Is.True);
    }

    // 3.4: while the gate holds, each member Released for this death in the rendezvous region turns Waiting at the
    // swap that writes it, with one start line: case warband, its slot as the spot, its assignment id now (a newer
    // one than at its release, so its hook 3 keeps the wait), the session id, Started now. The holder too.
    [Test]
    public void WhileHoldingReleasedMembersAtTheRendezvousTurnWaiting()
    {
        RpWarbandMember[] members =
        {
            Member(Released(), 240_000),
            Member(Released(), 120_000, slot: SecondSlot, assignmentId: "albion-40-13-RvR"),
        };
        RpWarbandGate gate = Gate(members);
        Assert.That(gate, Is.EqualTo(new RpWarbandGate(true, true, March, 240_000)));

        RpWaitChange[] changes = Marks(gate, members);

        Assert.That(changes, Has.Length.EqualTo(2));
        AssertTurnedWaiting(changes[0], members[0]);
        AssertTurnedWaiting(changes[1], members[1]);
        Assert.That(changes[0].Next.Spot, Is.EqualTo(BorderKeepSlot));
        Assert.That(changes[1].Next.Spot, Is.EqualTo(SecondSlot));
        Assert.That(changes[1].Next.AssignmentId, Is.EqualTo("albion-40-13-RvR"));
        Assert.That(changes[1].Next.SessionId, Is.EqualTo("albion-7f3a-007"));
        Assert.That(changes[1].Next.ReleasePoint, Is.EqualTo(Bind));
        AssertKept(LaterTurn(changes[1].Next, assignmentId: "albion-40-13-RvR"), changes[1].Next);
    }

    // 3.4, a ruling (the spec's gate has no time-left condition): while the gate holds, a member Released for this
    // death in the rendezvous region but worth points already (time left 0) stays Released, as a first look skips a
    // bot already worth points with no line: no wait starts and no start line is logged. The gate's opening latches
    // it with no line.
    [Test]
    public void WhileHoldingAReleasedMemberAlreadyWorthStaysReleased()
    {
        RpWarbandMember[] members =
        {
            Member(Released(), 240_000),
            Member(Released(), 0, slot: SecondSlot),
        };
        RpWarbandGate gate = Gate(members);
        Assert.That(gate, Is.EqualTo(new RpWarbandGate(true, true, March, 240_000)));

        RpWaitChange[] changes = Marks(gate, members);

        Assert.That(changes, Has.Length.EqualTo(2));
        AssertTurnedWaiting(changes[0], members[0]);
        AssertKept(changes[1], members[1].Marker);

        RpWarbandMember[] opening = { members[0] with { TimeLeft = March }, members[1] };
        gate = Gate(opening);
        Assert.That(gate.Waits, Is.False);
        AssertLatched(Marks(gate, opening)[1], members[1].Marker, RpWaitAction.None, RpWaitReason.None);
    }

    // 3.4: a member already Waiting is not written again while the gate holds: on later passes (once a second) its
    // marker stays the same reference and no second start is logged, and it still holds the gate.
    [Test]
    public void AWaitingMemberIsNotWrittenAgain()
    {
        RpWaitSlot slot = SlotWith(Released());
        RpWarbandMember[] first = { Member(slot.Current, 240_000) };
        RpWaitChange start = Marks(Gate(first), first)[0];
        Assert.That(start.Action, Is.EqualTo(RpWaitAction.Start));
        Assert.That(slot.TrySwap(start.Before, start.Next), Is.True);

        foreach (long timeLeft in new[] { 239_000L, 238_000L })
        {
            RpWarbandMember[] later = { Member(slot.Current, timeLeft) };
            RpWarbandGate gate = Gate(later);

            Assert.That(gate, Is.EqualTo(new RpWarbandGate(true, true, March, timeLeft)));
            AssertNothingWritten(Marks(gate, later), later);
        }
    }

    // 3.4: a member released to its capital stays Released while it is there and still holds the gate (its death in
    // the frontier sets the march); on the first pass after it enters the rendezvous region it turns Waiting at its
    // slot, the region of its wait the rendezvous region.
    [Test]
    public void AMemberInAnotherRegionStaysReleasedThenTurnsWaitingWhenItArrives()
    {
        RpWarbandMember atSlot = Member(Waiting(RpWaitCase.Warband), 150_000);
        RpWarbandMember away = Member(ReleasedInCamelot(), 280_000, region: CamelotRegion, slot: SecondSlot);
        RpWarbandMember[] members = { atSlot, away };
        RpWarbandGate gate = Gate(members);

        Assert.That(gate, Is.EqualTo(new RpWarbandGate(true, true, March, 280_000)));
        AssertNothingWritten(Marks(gate, members), members);

        RpWarbandMember arrived = away with { Region = 1, TimeLeft = 220_000 };
        members = new[] { atSlot with { TimeLeft = 90_000 }, arrived };
        gate = Gate(members);

        Assert.That(gate, Is.EqualTo(new RpWarbandGate(true, true, March, 220_000)));
        RpWaitChange[] changes = Marks(gate, members);
        AssertKept(changes[0], atSlot.Marker);
        AssertTurnedWaiting(changes[1], arrived);
        Assert.That(changes[1].Next.Region, Is.EqualTo(1));
        Assert.That(changes[1].Next.ReleaseRegion, Is.EqualTo(CamelotRegion));
    }

    // 3.4: while the gate holds, a member resurrected in the field (no marker for its death: none, or its previous
    // death's) gets none, and a member whose marker is Left for this death (its first look skipped, or its hook 3
    // ended its wait) stays Left: it walks back with the regroup and fights on.
    [Test]
    public void AResurrectedOrLeftMemberGetsNoMarker()
    {
        RpWarbandMember[] members =
        {
            Member(Released(), 240_000),
            Member(null, 250_000, slot: SecondSlot),
            Member(PreviousDeathsMarker(), 250_000, slot: SecondSlot),
            Member(Released() with { Phase = RpWaitPhase.Left, Case = RpWaitCase.Frontier }, 200_000, slot: ThirdSlot),
            Member(Waiting(RpWaitCase.Warband) with { Phase = RpWaitPhase.Left }, 200_000),
        };
        RpWarbandGate gate = Gate(members);

        Assert.That(gate, Is.EqualTo(new RpWarbandGate(true, true, March, 240_000)));
        RpWaitChange[] changes = Marks(gate, members);
        AssertTurnedWaiting(changes[0], members[0]);
        for (int i = 1; i < members.Length; i++)
            AssertKept(changes[i], members[i].Marker);
    }

    // 3.4: when the gate opens, every member's marker for its current death is latched Left: a Waiting one with its
    // leave (due), a Released one still worth nothing with its skip (trip), wherever it stands, and a Released one
    // worth points already with no line. An older death's marker (Left, 3.7) and no marker are not touched.
    [Test]
    public void OpeningLatchesEveryMemberForThisDeath()
    {
        RpWarbandMember[] members =
        {
            Member(Waiting(RpWaitCase.Warband), March),
            Member(Released(), 30_000, slot: SecondSlot),
            Member(ReleasedInCamelot(), 20_000, region: CamelotRegion, slot: ThirdSlot),
            Member(Released(), 0, slot: ThirdSlot),
            Member(PreviousDeathsMarker(), 250_000),
            Member(null, 250_000),
        };
        RpWarbandGate gate = Gate(members);

        Assert.That(gate, Is.EqualTo(new RpWarbandGate(false, true, March, March)));
        RpWaitChange[] changes = Marks(gate, members);
        Assert.That(changes, Has.Length.EqualTo(6));
        AssertLatched(changes[0], members[0].Marker, RpWaitAction.Leave, RpWaitReason.Due);
        AssertLatched(changes[1], members[1].Marker, RpWaitAction.Skip, RpWaitReason.Trip);
        AssertLatched(changes[2], members[2].Marker, RpWaitAction.Skip, RpWaitReason.Trip);
        AssertLatched(changes[3], members[3].Marker, RpWaitAction.None, RpWaitReason.None);
        AssertKept(changes[4], members[4].Marker);
        AssertKept(changes[5], null);
    }

    // 3.4, 3.5: a member whose wait its hook 3 has already ended (its force's muster order: called) gets no new wait
    // while the gate holds and no second leave (due) when it opens.
    [Test]
    public void AMarkerHook3AlreadyEndedGetsNoSecondLeave()
    {
        RpWaitSlot slot = SlotWith(Waiting(RpWaitCase.Warband));
        RpWaitChange called = LaterTurn(slot.Current, musterOrder: true);
        Assert.That(called.Reason, Is.EqualTo(RpWaitReason.Called));
        Assert.That(slot.TrySwap(called.Before, called.Next), Is.True);
        RpWarbandMember ended = Member(slot.Current, 200_000);

        RpWarbandMember[] holding = { ended, Member(Released(), 240_000, slot: SecondSlot) };
        RpWarbandGate gate = Gate(holding);
        Assert.That(gate.Waits, Is.True);
        AssertKept(Marks(gate, holding)[0], slot.Current);

        RpWarbandMember[] opening = { ended with { TimeLeft = 40_000 }, Member(Released(), 30_000, slot: SecondSlot) };
        gate = Gate(opening);
        Assert.That(gate.Waits, Is.False);
        AssertKept(Marks(gate, opening)[0], slot.Current);
    }

    // 7.2: the gate decides from the markers it read and swaps each change against its read. A marker that turns Left
    // on another thread in between (a player's invite while Released; its own hook 3 while Waiting, here out of its
    // group) stays Left: the gate's swap fails, and it logs nothing.
    [Test]
    public void AMarkerThatTurnsLeftBetweenReadAndWriteStaysLeft()
    {
        RpWaitSlot released = SlotWith(Released());
        RpWarbandMember[] holding = { Member(released.Current, 240_000) };
        RpWaitChange start = Marks(Gate(holding), holding)[0];
        Assert.That(start.Action, Is.EqualTo(RpWaitAction.Start));
        RpWaitChange invited = released.Apply(marker => RpTimerWait.JoinedGroup(marker, 3, true));
        Assert.That(released.TrySwap(start.Before, start.Next), Is.False);
        Assert.That(released.Current, Is.SameAs(invited.Next));
        Assert.That(released.Current.Phase, Is.EqualTo(RpWaitPhase.Left));

        RpWaitSlot waiting = SlotWith(Waiting(RpWaitCase.Warband));
        RpWarbandMember[] opening = { Member(waiting.Current, March) };
        RpWaitChange due = Marks(Gate(opening), opening)[0];
        Assert.That(due.Reason, Is.EqualTo(RpWaitReason.Due));
        RpWaitChange changed = LaterTurn(waiting.Current, inGroup: false);
        Assert.That(waiting.TrySwap(changed.Before, changed.Next), Is.True);
        Assert.That(waiting.TrySwap(due.Before, due.Next), Is.False);
        Assert.That(waiting.Current, Is.SameAs(changed.Next));
        Assert.That(waiting.Current.Phase, Is.EqualTo(RpWaitPhase.Left));
    }

    // 3.7: a member killed while waiting has its death count raised before the Dying handler latches its marker Left
    // (died). Before the handler and after it, the gate neither holds for that marker nor writes it, holding or
    // opening: no second leave.
    [Test]
    public void TheGateIgnoresAMarkerLatchedByADeath()
    {
        RpWaitSlot slot = SlotWith(Waiting(RpWaitCase.Warband));
        RpWarbandMember released = Member(Released(), 30_000, slot: SecondSlot);
        RpWarbandMember killed = Member(slot.Current, 300_000, deathCount: 4);

        RpWarbandMember[] members = { killed, released };
        RpWarbandGate gate = Gate(members);
        Assert.That(gate, Is.EqualTo(new RpWarbandGate(false, true, March, 30_000)));
        AssertKept(Marks(gate, members)[0], killed.Marker);

        RpWaitChange died = slot.Apply(marker => RpTimerWait.Died(marker, 4));
        Assert.That(died.Reason, Is.EqualTo(RpWaitReason.Died));
        RpWarbandMember latched = killed with { Marker = slot.Current };
        members = new[] { latched, released };
        gate = Gate(members);
        Assert.That(gate, Is.EqualTo(new RpWarbandGate(false, true, March, 30_000)));
        AssertKept(Marks(gate, members)[0], slot.Current);

        members = new[] { latched, released with { TimeLeft = 240_000 } };
        gate = Gate(members);
        Assert.That(gate, Is.EqualTo(new RpWarbandGate(true, true, March, 240_000)));
        AssertKept(Marks(gate, members)[0], slot.Current);
    }

    // The four cases of wait, in the order of section 3.
    private static readonly RpWaitCase[] EveryWaitCase =
        { RpWaitCase.Frontier, RpWaitCase.Siege, RpWaitCase.Warband, RpWaitCase.Battleground };

    // Hooks 5 and 6 ask whether the bot counts as waiting (2.4), for death count 3: the switch on, 240 s left on its
    // timer, standing at the marker's spot in its region with its assignment id, not in a player's group, in a group
    // only for a warband marker, and no battleground arrival (the wiring gives one only for a Released marker in a
    // battleground region). Each test sets what it is about.
    private static bool Counts(RpWaitMarker marker, bool enabled = true, int deathCount = 3, long timeLeft = TimeLeft,
        ushort? region = null, Vector3? position = null, string assignmentId = null, bool playerLed = false,
        bool? inGroup = null, Vector3? battlegroundArrival = null) =>
        RpTimerWait.IsWaiting(enabled, marker, deathCount, timeLeft, region ?? marker.Region, position ?? marker.Spot,
            assignmentId ?? marker.AssignmentId, playerLed, inGroup ?? (marker.Case == RpWaitCase.Warband),
            battlegroundArrival);

    // 2.4, section 4: counting as waiting has no clock. No time goes in but the time left, so the turns a waiting bot
    // spends fighting, casting or rebuffing, when no hook runs, never let it charge or be recruited. It counts 60 s
    // after its wait started, 5 min after on a server whose rp_worth_seconds is 600, and in its last millisecond, at
    // its spot or 3,000 from it in its wait's region, where a fight took it.
    [TestCase(RpWaitCase.Frontier)]
    [TestCase(RpWaitCase.Siege)]
    [TestCase(RpWaitCase.Warband)]
    [TestCase(RpWaitCase.Battleground)]
    public void AWaitingBotCountsWithNoClock(RpWaitCase waitCase)
    {
        RpWaitMarker waiting = Waiting(waitCase);
        long minuteLater = RpTimerWait.WorthlessForMilliseconds(DeathTick, waiting.Started + 60_000, RpWorthSeconds);
        long fiveMinutesLater = RpTimerWait.WorthlessForMilliseconds(DeathTick, waiting.Started + 300_000, 600);
        Assert.That(minuteLater, Is.EqualTo(220_000));
        Assert.That(fiveMinutesLater, Is.EqualTo(280_000));

        var foughtAway = new Vector3(waiting.Spot.X + 3_000, waiting.Spot.Y, waiting.Spot.Z);
        foreach (long timeLeft in new[] { minuteLater, fiveMinutesLater, 1L })
        {
            Assert.That(Counts(waiting, timeLeft: timeLeft), Is.True);
            Assert.That(Counts(waiting, timeLeft: timeLeft, position: foughtAway), Is.True);
        }
    }

    // 2.4: every part must hold, so each mismatch alone stops a wait counting, whatever its case: the switch off
    // (section 6), no marker (a resurrected bot, a PvE goal), a marker for another death (killed again: the count is
    // raised before the Dying handler runs), time left 0 (worth points: it charges what it sees, section 4), another
    // region or assignment id than its wait's (hook 3 ends it on its next turn), a player's group (3.8), or the marker
    // Left (the wait ended).
    [TestCase("switch off")]
    [TestCase("no marker")]
    [TestCase("another death")]
    [TestCase("time left 0")]
    [TestCase("another region")]
    [TestCase("another assignment id")]
    [TestCase("player-led")]
    [TestCase("Left")]
    public void EachMismatchStopsItCounting(string mismatch)
    {
        foreach (RpWaitCase waitCase in EveryWaitCase)
        {
            RpWaitMarker waiting = Waiting(waitCase);
            Assert.That(Counts(waiting), Is.True, $"{waitCase}");
            bool counts = mismatch switch
            {
                "switch off" => Counts(waiting, enabled: false),
                "no marker" => RpTimerWait.IsWaiting(true, null, 3, TimeLeft, waiting.Region, waiting.Spot,
                    waiting.AssignmentId, false, waitCase == RpWaitCase.Warband, null),
                "another death" => Counts(waiting, deathCount: 4),
                "time left 0" => Counts(waiting, timeLeft: 0),
                "another region" => Counts(waiting, region: CamelotRegion),
                "another assignment id" => Counts(waiting, assignmentId: "albion-40-13-RvR"),
                "player-led" => Counts(waiting, playerLed: true),
                "Left" => Counts(waiting with { Phase = RpWaitPhase.Left }),
                _ => throw new ArgumentOutOfRangeException(nameof(mismatch)),
            };
            Assert.That(counts, Is.False, $"{waitCase}");
        }
    }

    // 2.4: a warband wait counts only while the bot is still in a group (a warband that disbands mid-wait ends its
    // wait, section 1). The group matters for no other wait: a frontier, siege or battleground wait, and a warband
    // member's wait converted to a siege wait (3.4), count in a group (a siege party's merge, section 4) or out of one.
    [Test]
    public void AWaitingWarbandWithNoGroupDoesNotCount()
    {
        RpWaitMarker held = Waiting(RpWaitCase.Warband);
        Assert.That(Counts(held, inGroup: true), Is.True);
        Assert.That(Counts(held, inGroup: false), Is.False);

        RpWaitMarker converted = held with { Case = RpWaitCase.Siege, EventKeepId = "rvr-keep-50", Started = Now };
        RpWaitMarker[] others =
        {
            Waiting(RpWaitCase.Frontier), Waiting(RpWaitCase.Siege), Waiting(RpWaitCase.Battleground), converted,
        };
        foreach (RpWaitMarker waiting in others)
        {
            Assert.That(Counts(waiting, inGroup: false), Is.True, $"{waiting.Case}");
            Assert.That(Counts(waiting, inGroup: true), Is.True, $"{waiting.Case}");
        }
    }

    // 2.4, 3.1: a battleground bot released outside (here in Camelot) counts from the moment the teleporter lands it,
    // before its first look, so the threat scan of its first think inside doesn't charge an enemy it only sees: in
    // any battleground region, within 2,500 of its realm's arrival point there (horizontally: 400 higher). Not with
    // no arrival known, not in another region than a battleground's with one, and not yet at its release point.
    [TestCase(0f, true)]
    [TestCase(2_500f, true)]
    [TestCase(2_501f, false)]
    [TestCase(2_600f, false)]
    public void AReleasedBotNearItsBattlegroundArrivalCounts(float away, bool counts)
    {
        RpWaitMarker released = ReleasedForTheBattleground();
        var standing = new Vector3(AlbionArrival.X, AlbionArrival.Y - away, AlbionArrival.Z + 400);
        for (ushort battleground = RpTimerWait.FirstBattlegroundRegion;
             battleground <= RpTimerWait.LastBattlegroundRegion; battleground++)
        {
            Assert.That(Counts(released, region: battleground, position: standing, battlegroundArrival: AlbionArrival),
                Is.EqualTo(counts), $"region {battleground}");
            Assert.That(Counts(released, region: battleground, position: standing), Is.False);
        }

        Assert.That(Counts(released, region: 1, position: standing, battlegroundArrival: AlbionArrival), Is.False);
        Assert.That(Counts(released), Is.False);
    }

    // 2.4, 3.2: a bot released at a bind in its own frontier (Albion's, Midgard's or Hibernia's) counts before its
    // first look while it stands within 750 of its release point there (horizontally: 300 lower), the first look's own
    // gate; not in another region at the same coordinates.
    [TestCase(0f, true)]
    [TestCase(750f, true)]
    [TestCase(751f, false)]
    [TestCase(800f, false)]
    public void AReleasedBotNearItsFrontierBindCounts(float away, bool counts)
    {
        var standing = new Vector3(Bind.X + away, Bind.Y, Bind.Z - 300);
        ushort[] frontiers = { RpTimerWait.AlbionFrontier, RpTimerWait.MidgardFrontier, RpTimerWait.HiberniaFrontier };
        foreach (ushort frontier in frontiers)
        {
            RpWaitMarker released = Released() with { ReleaseRegion = frontier, Region = frontier };
            Assert.That(Counts(released, position: standing), Is.EqualTo(counts), $"region {frontier}");

            ushort another = frontier == RpTimerWait.AlbionFrontier
                ? RpTimerWait.MidgardFrontier
                : RpTimerWait.AlbionFrontier;
            Assert.That(Counts(released, region: another, position: standing), Is.False);
        }
    }

    // 2.4, section 1: a frontier invader, or an attacker of a keep in an enemy frontier, releases in its capital
    // (Camelot, Jordheim or Tir na Nog: regions 10, 101 and 201; Camelot's point serves for each, only the region
    // matters), never in the frontier of its fight. So its Released marker never counts: not at its bind in the
    // capital, and not later in any frontier, at its release point's coordinates or at a frontier bind.
    [Test]
    public void AnInvadersReleasedMarkerNeverCounts()
    {
        ushort[] frontiers = { RpTimerWait.AlbionFrontier, RpTimerWait.MidgardFrontier, RpTimerWait.HiberniaFrontier };
        foreach (ushort capital in new ushort[] { CamelotRegion, 101, 201 })
        {
            RpWaitMarker released = ReleasedInCamelot() with { ReleaseRegion = capital, Region = capital };
            Assert.That(Counts(released), Is.False, $"region {capital}");
            foreach (ushort frontier in frontiers)
            {
                Assert.That(Counts(released, region: frontier), Is.False);
                Assert.That(Counts(released, region: frontier, position: Bind), Is.False);
            }
        }

        Assert.That(Counts(Released()), Is.True);
    }

    // 2.4: a Released marker counts under the same conditions as a wait: not with its time left at 0 (worth points
    // already), for an older death (killed again before its first look), with another assignment id, in a player's
    // group, or with the switch off; at a frontier bind or on a battleground arrival point alike.
    [Test]
    public void AReleasedMarkerOtherwiseOffDoesNotCount()
    {
        RpWaitMarker atBind = Released();
        Assert.That(Counts(atBind), Is.True);
        Assert.That(Counts(atBind, timeLeft: 0), Is.False);
        Assert.That(Counts(atBind, deathCount: 4), Is.False);
        Assert.That(Counts(atBind, assignmentId: "albion-40-13-RvR"), Is.False);
        Assert.That(Counts(atBind, playerLed: true), Is.False);
        Assert.That(Counts(atBind, enabled: false), Is.False);

        // The battleground bot landed on its realm's arrival point in Thidranki, its first look still to come.
        RpWaitMarker landed = ReleasedForTheBattleground();
        bool Landed(bool enabled = true, int deathCount = 3, long timeLeft = TimeLeft, string assignmentId = null,
            bool playerLed = false) =>
            Counts(landed, enabled, deathCount, timeLeft, Thidranki, AlbionArrival, assignmentId, playerLed,
                battlegroundArrival: AlbionArrival);
        Assert.That(Landed(), Is.True);
        Assert.That(Landed(timeLeft: 0), Is.False);
        Assert.That(Landed(deathCount: 4), Is.False);
        Assert.That(Landed(assignmentId: "albion-20-13-Battleground"), Is.False);
        Assert.That(Landed(playerLed: true), Is.False);
        Assert.That(Landed(enabled: false), Is.False);
    }

    // 3.7, 2.4: a bot killed while waiting, or while released before its first look, stops counting at once: its
    // death count is raised before the Dying handler runs, and the handler then latches the old marker Left.
    // Resurrected where it fell (no release), it has no marker for the new death and charges and is recruited as any
    // bot; released instead, hook 3 notes the new death and it counts again at its bind.
    [Test]
    public void AMarkerLatchedByADeathDoesNotCount()
    {
        RpWaitMarker[] markers =
        {
            Waiting(RpWaitCase.Frontier), Waiting(RpWaitCase.Siege), Waiting(RpWaitCase.Warband), Released(),
        };
        foreach (RpWaitMarker before in markers)
        {
            RpWaitSlot slot = SlotWith(before);
            Assert.That(Counts(slot.Current), Is.True);
            Assert.That(Counts(slot.Current, deathCount: 4), Is.False);

            slot.Apply(marker => RpTimerWait.Died(marker, 4));
            RpWaitMarker left = slot.Current;
            Assert.That(left.Phase, Is.EqualTo(RpWaitPhase.Left));
            Assert.That(Counts(left, deathCount: 4), Is.False);
            Assert.That(Counts(left), Is.False);

            AssertKept(ReleaseTurn(left, deathCount: 4, returning: false), left);
            Assert.That(Counts(left, deathCount: 4), Is.False);

            RpWaitChange noted = ReleaseTurn(left, deathCount: 4);
            Assert.That(slot.TrySwap(noted.Before, noted.Next), Is.True);
            Assert.That(Counts(slot.Current, deathCount: 4), Is.True);
        }
    }
}

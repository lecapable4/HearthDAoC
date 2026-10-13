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
}

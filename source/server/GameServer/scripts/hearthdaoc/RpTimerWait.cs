using System;
using System.Collections.Generic;
using System.Numerics;
using System.Threading;

namespace DOL.GS.HearthDAoC;

// HearthDAoC: gamebots come back worth realm points, stage 1 (spec docs/fork/specs/2026-10-13-rp-timer-waits-design.md).
// A gamebot released after a death in RvR or a battleground waits at a safe spot and leaves when its time left is no
// more than its trip back to the fight, so it arrives just as it is worth realm points again; a frontier warband leaves
// together. Every decision is made here, on plain values, with no server state. RpTimerWaitScript is the game wiring
// (the switch, hooks 3-6, the death and group handlers, the log); RpTimerWaitController.cs is the controller side
// (hooks 1-2).

/// <summary>Where a bot's wait stands for one death (2.4).</summary>
public enum RpWaitPhase
{
    /// <summary>Hook 3 saw the release; the first look (hooks 1-2) or the warband gate is still to come.</summary>
    Released,
    /// <summary>A wait runs.</summary>
    Waiting,
    /// <summary>The latch: no hook stops the bot again for this death.</summary>
    Left,
}

/// <summary>Which wait (section 3). <see cref="None"/>: a Released marker no first look has classified yet.</summary>
public enum RpWaitCase
{
    None,
    Battleground,
    Frontier,
    Siege,
    Warband,
}

/// <summary>The log line a marker change writes (10.5). Convert writes two: leave reason=battle, then start case=siege.</summary>
public enum RpWaitAction
{
    None,
    Start,
    Skip,
    Leave,
    Convert,
}

/// <summary>Why a wait was skipped or ended (10.5). Each has one log word: see RpTimerWaitScript.ReasonWord.</summary>
public enum RpWaitReason
{
    None,
    Trip,
    OtherRegion,
    MovedAway,
    Relic,
    NoTarget,
    Due,
    Off,
    Changed,
    Called,
    PlayerGroup,
    Battle,
    Died,
}

/// <summary>What hooks 1-2 do on one turn (7.1, Decide).</summary>
public enum RpWaitVerdict
{
    Ignore,
    Skip,
    Start,
    Convert,
    Hold,
    Leave,
}

/// <summary>
/// One bot's wait for one death (2.4). Immutable: every write swaps in a new marker (a <c>with</c> copy) through
/// <see cref="RpWaitSlot.TrySwap"/>. Compare markers by reference (<see cref="object.ReferenceEquals"/>), never with
/// <c>==</c>: a record's <c>==</c> compares values.
/// </summary>
/// <param name="DeathCount">The <c>PersistentRecord.DeathCount</c> this marker is for (raised at every death, GB:953).</param>
/// <param name="Phase">Released, Waiting or Left.</param>
/// <param name="Case">The wait's case; None while Released.</param>
/// <param name="ReleaseRegion">The region the bot stood in at hook 3's note (its bind's, or its capital's).</param>
/// <param name="ReleasePoint">Where it stood then: the release point.</param>
/// <param name="Region">The region of the wait (the release region until a wait starts).</param>
/// <param name="Spot">The spot of the wait: the battleground slot, the release point, or the warband slot.</param>
/// <param name="AssignmentId">The bot's <c>PersistentRecord.ObjectiveAssignmentId</c> at the note, then at the wait's start.</param>
/// <param name="SessionId">The warband's session id (warband waits, and a drafted member's siege wait); else null.</param>
/// <param name="EventKeepId">The event keep (<c>_rvrDestination.Id</c>) of a siege wait; else null.</param>
/// <param name="Started">GameLoop time the wait started (Start or Convert), for the log; 0 while Released.</param>
public sealed record RpWaitMarker(
    int DeathCount,
    RpWaitPhase Phase,
    RpWaitCase Case,
    ushort ReleaseRegion,
    Vector3 ReleasePoint,
    ushort Region,
    Vector3 Spot,
    string AssignmentId,
    string SessionId,
    string EventKeepId,
    long Started);

/// <summary>
/// The per-bot holder of the current marker (7.2), kept in the bot's TempProperty <c>hearthdaoc.rp.wait</c>. Bot brains
/// tick in parallel and the warband gate writes other members' markers, so every write is a compare-and-set.
/// </summary>
public sealed class RpWaitSlot
{
    private RpWaitMarker _marker;

    /// <summary>The marker now (null until the first release is noted).</summary>
    public RpWaitMarker Current => Volatile.Read(ref _marker);

    /// <summary>Swaps in <paramref name="next"/> if the marker is still <paramref name="expected"/> (by reference), by
    /// <c>Interlocked.CompareExchange</c>. False, and nothing changed, when another writer swapped first.</summary>
    public bool TrySwap(RpWaitMarker expected, RpWaitMarker next) =>
        ReferenceEquals(Interlocked.CompareExchange(ref _marker, next, expected), expected);

    /// <summary>The handlers' retry (3.7, 3.8): reads the marker, asks <paramref name="decide"/>, and returns its change
    /// once the change keeps the marker as it is (nothing to write) or its swap succeeds; after a lost swap it reads
    /// again and decides again.</summary>
    public RpWaitChange Apply(Func<RpWaitMarker, RpWaitChange> decide)
    {
        while (true)
        {
            RpWaitMarker read = Current;
            RpWaitChange change = decide(read);
            if (ReferenceEquals(change.Next, read) || TrySwap(read, change.Next))
                return change;
        }
    }
}

/// <summary>The death record (3.7), kept in the bot's TempProperty <c>hearthdaoc.rp.death</c> by the Dying handler.</summary>
/// <param name="DeathCount">The death count after this death.</param>
/// <param name="Region">Where it died.</param>
/// <param name="Position">Where it died.</param>
/// <param name="Tick">GameLoop time of the death.</param>
/// <param name="TimerValue">The realm point timer key's value as the death ends (ARPR:90 has written it, if it ran);
/// the next death's <c>worth</c> is read from it.</param>
public sealed record RpDeathRecord(int DeathCount, ushort Region, Vector3 Position, long Tick, long TimerValue);

/// <summary>A marker change: Note, Died, JoinedGroup, and each member of WarbandMarks. <see cref="Next"/> is
/// <see cref="Before"/> itself (the same reference) when nothing is to be written.</summary>
public readonly record struct RpWaitChange(RpWaitMarker Before, RpWaitMarker Next, RpWaitAction Action, RpWaitReason Reason)
{
    /// <summary>Nothing to write.</summary>
    public static RpWaitChange Keep(RpWaitMarker marker) => new(marker, marker, RpWaitAction.None, RpWaitReason.None);

    /// <summary>True when <see cref="Next"/> is another marker than <see cref="Before"/>.</summary>
    public bool Changes => !ReferenceEquals(Before, Next);
}

/// <summary>What hooks 1-2 see on one turn (Decide's input besides the marker and the clock).</summary>
/// <param name="Case">The hook's case: Battleground (hook 1); Siege (a battle with a keep plan), Warband (a dynamic
/// warband outside battle) or Frontier (anything else) for hook 2.</param>
/// <param name="Region">The bot's region now.</param>
/// <param name="Position">The bot's position now.</param>
/// <param name="AssignmentId">Its <c>PersistentRecord.ObjectiveAssignmentId</c> now.</param>
/// <param name="EventKeepId">A siege's event keep id (<c>_rvrDestination.Id</c>); null for other cases.</param>
/// <param name="Relic">A relic carrier, a destination starting <c>rvr-relic-carrier-</c>, or a battle with no keep plan.</param>
/// <param name="HasTarget">A trip target is known.</param>
/// <param name="TargetRegion">The target's region (when known).</param>
/// <param name="Arrival">Battleground only: its realm's <c>BotArrival</c> (the 2,500 first-look gate).</param>
/// <param name="BattlegroundSlot">Battleground only: the spot a Start stores (slot <c>1 + ObjectID % 12</c>).</param>
public readonly record struct RpWaitLook(
    RpWaitCase Case,
    ushort Region,
    Vector3 Position,
    string AssignmentId,
    string EventKeepId,
    bool Relic,
    bool HasTarget,
    ushort TargetRegion,
    Vector3 Arrival,
    Vector3 BattlegroundSlot);

/// <summary>Hooks 1-2's decision for one turn. <see cref="Next"/> is the marker to swap in (<see cref="Before"/> itself
/// for Ignore and Hold). <see cref="WalkBack"/>: a Start more than <see cref="RpTimerWait.SpotTolerance"/> from its
/// spot, or a Hold more than <see cref="RpTimerWait.WalkBackBeyond"/> from it; false for a Convert.</summary>
public readonly record struct RpWaitDecision(
    RpWaitVerdict Verdict,
    RpWaitReason Reason,
    RpWaitMarker Before,
    RpWaitMarker Next,
    RpWaitAction Action,
    bool WalkBack);

/// <summary>One warband member as the gate sees it (3.4).</summary>
/// <param name="Marker">Its marker now (null: none).</param>
/// <param name="DeathCount">Its death count now.</param>
/// <param name="TimeLeft">Its time left now (ms).</param>
/// <param name="Death">Its death record (null: none).</param>
/// <param name="Region">Its region now.</param>
/// <param name="Slot">Its rendezvous slot (<c>RendezvousFormationPoint</c>).</param>
/// <param name="AssignmentId">Its assignment id now.</param>
/// <param name="BestSpeed">Its best speed (units/s).</param>
public readonly record struct RpWarbandMember(
    RpWaitMarker Marker,
    int DeathCount,
    long TimeLeft,
    RpDeathRecord Death,
    ushort Region,
    Vector3 Slot,
    string AssignmentId,
    double BestSpeed);

/// <summary>The warband gate's verdict (3.4). <see cref="Writes"/> is false (and the gate writes nothing) with the switch
/// off, a session that is not RvR, or a committed force. <see cref="MarchMilliseconds"/> and
/// <see cref="HolderTimeLeft"/> are 0 when no member holds the gate.</summary>
public readonly record struct RpWarbandGate(bool Waits, bool Writes, long MarchMilliseconds, long HolderTimeLeft);

/// <summary>The decisions (7.1). Plain values in and out; no server state.</summary>
public static class RpTimerWait
{
    /// <summary>3.2: a frontier or siege first look within this of the release point.</summary>
    public const int BindGate = 750;
    /// <summary>3.1: a battleground first look within this of its realm's BotArrival.</summary>
    public const int ArrivalGate = 2_500;
    /// <summary>3.4: a drafted warband member's first look as a siege member within this of its slot.</summary>
    public const int SlotGate = 200;
    /// <summary>Section 4: a waiting bot farther than this from its spot walks back.</summary>
    public const int WalkBackBeyond = 200;
    /// <summary>3.1, section 4: a Start walks to its spot when farther than this (IssuePath's own arrival radius,
    /// WBC:5176-5180), so a battleground bot landed on slot 0 walks to its slot 160-330 away.</summary>
    public const int SpotTolerance = 48;
    /// <summary>3.1: enemy roam anchors lie this share of the way from an arrival point to the central keep (BG:124-125).</summary>
    public const float ContactShare = 0.6f;
    /// <summary>3.1: roamers patrol within this of their anchor (BG:135).</summary>
    public const int PatrolRadius = 900;
    /// <summary>3.1: the threat scan's reach (WBC:35, TargetSearchRadius).</summary>
    public const int ScanRadius = 5_000;
    /// <summary>2.3: the shortest think wake.</summary>
    public const int WakeFloorMilliseconds = 250;
    /// <summary>2.4: the battleground regions (BattlegroundBrackets.IsBattlegroundRegion).</summary>
    public const ushort FirstBattlegroundRegion = 250, LastBattlegroundRegion = 253;
    /// <summary>2.4: the three frontier regions (Albion, Midgard, Hibernia).</summary>
    public const ushort AlbionFrontier = 1, MidgardFrontier = 100, HiberniaFrontier = 200;

    // 2.4: 250-253.
    public static bool IsBattlegroundRegion(ushort region) =>
        region is >= FirstBattlegroundRegion and <= LastBattlegroundRegion;

    // 2.4: 1, 100 or 200.
    public static bool IsFrontierRegion(ushort region) =>
        region is AlbionFrontier or MidgardFrontier or HiberniaFrontier;

    // 2.2, 2.4, 3.1: the horizontal (X, Y) distance; every gate, walk-back and trip distance uses it.
    public static double Distance2D(Vector3 a, Vector3 b)
    {
        double dx = (double)a.X - b.X, dy = (double)a.Y - b.Y;
        return Math.Sqrt(dx * dx + dy * dy);
    }

    // 2.1: ms until worth realm points (0 = worth), exactly as ARPR:82-86: 0 with no death on record (last < 0) or an
    // interval of 0 (rp_worth_seconds <= 0); else interval - (now - last), kept within 0 to interval.
    public static long WorthlessForMilliseconds(long lastDeathTick, long now, int rpWorthSeconds)
    {
        long interval = Math.Max(0, rpWorthSeconds) * 1000L;
        if (lastDeathTick < 0 || interval == 0)
            return 0;
        return Math.Clamp(interval - (now - lastDeathTick), 0, interval);
    }

    // 2.2: the largest of the live MaxSpeed, MaxSpeedBase, and MaxSpeedBase x bestOwnSpeedValue / 100 (units/s).
    public static double BestSpeed(short maxSpeed, short maxSpeedBase, double bestOwnSpeedValue) =>
        Math.Max(Math.Max(maxSpeed, maxSpeedBase), maxSpeedBase * bestOwnSpeedValue / 100);

    // 2.2: distance / speed in ms, rounded down; long.MaxValue when speed <= 0 (no speed: it never waits).
    public static long TripMilliseconds(double distance, double unitsPerSecond)
    {
        if (unitsPerSecond <= 0)
            return long.MaxValue;
        double milliseconds = Math.Floor(distance * 1000 / unitsPerSecond);
        return milliseconds < long.MaxValue ? (long)milliseconds : long.MaxValue;
    }

    // 3.1: the point max(0, 0.6 x |AC| - 900 - 5,000) from the arrival A toward the central keep C (A itself for a
    // short field, or when A = C).
    public static Vector2 FirstContactPoint(Vector2 arrival, Vector2 centralKeep)
    {
        Vector2 toKeep = centralKeep - arrival;
        float length = toKeep.Length();
        float along = ContactShare * length - PatrolRadius - ScanRadius;
        return along > 0 ? arrival + toKeep * (along / length) : arrival;
    }

    // 2.3, 7.1: the game tick at which time left = trip: last + max(0, rp_worth_seconds) x 1000 - trip, the trip
    // clamped to 0..interval (no overflow with a trip of long.MaxValue).
    public static long LeaveTick(long lastDeathTick, int rpWorthSeconds, long tripMilliseconds)
    {
        long interval = Math.Max(0, rpWorthSeconds) * 1000L;
        return lastDeathTick + interval - Math.Clamp(tripMilliseconds, 0, interval);
    }

    // 2.3: the next think interval: max(250, leaveTick - now + ceil(tickDuration / 2)) when that is below
    // standardInterval, else standardInterval (17 ms at 30 ticks/s; 0 in tests, where TickDuration is 0).
    public static int ThinkWakeMilliseconds(long leaveTick, long now, double tickDurationMilliseconds, int standardInterval)
    {
        long wake = Math.Max(WakeFloorMilliseconds, leaveTick - now + (long)Math.Ceiling(tickDurationMilliseconds / 2));
        return wake < standardInterval ? (int)wake : standardInterval;
    }

    // 2.4: the latch. The marker read, Left (every other value kept, in a new marker), with the change's log action
    // and reason.
    private static RpWaitChange Latch(RpWaitMarker marker, RpWaitAction action, RpWaitReason reason) =>
        new(marker, marker with { Phase = RpWaitPhase.Left }, action, reason);

    // 3.5, hook 3. The rules, in order:
    // 1. A release (alive && returning): unchanged with the switch off, a goal other than RvR or Battleground, or a
    //    marker already for this death (Released or Left; a Waiting one goes to rule 2, the release flag up or not);
    //    else a new Released marker (DeathCount, Released, None, ReleaseRegion = Region = region, ReleasePoint = Spot
    //    = position, assignmentId, null, null, 0), action None.
    // 2. A Waiting marker for this death, in order: switch off: Left, Leave(Off); another assignment id or region than
    //    stored: Left, Leave(Changed); a Warband marker with !inGroup: Left, Leave(Changed); a Frontier marker with
    //    forceCommitted: Left, Leave(Called); a Siege or Warband marker with musterOrder: Left, Leave(Called).
    // 3. Anything else: unchanged.
    // Left = marker with { Phase = Left }. forceCommitted and musterOrder are read by the wiring only for a Waiting
    // marker for this death (Frontier: IsForceCommitted; Siege, Warband: GetRallyOrder != null); else false.
    public static RpWaitChange Note(bool enabled, RpWaitMarker marker, int deathCount, bool alive, bool returning,
        eAutonomousObjectiveKind goal, ushort region, Vector3 position, string assignmentId, bool inGroup,
        bool forceCommitted, bool musterOrder)
    {
        bool forThisDeath = marker != null && marker.DeathCount == deathCount;
        if (forThisDeath && marker.Phase == RpWaitPhase.Waiting)
        {
            if (!enabled)
                return Latch(marker, RpWaitAction.Leave, RpWaitReason.Off);
            if (assignmentId != marker.AssignmentId || region != marker.Region)
                return Latch(marker, RpWaitAction.Leave, RpWaitReason.Changed);
            if (marker.Case == RpWaitCase.Warband && !inGroup)
                return Latch(marker, RpWaitAction.Leave, RpWaitReason.Changed);
            if (marker.Case == RpWaitCase.Frontier && forceCommitted)
                return Latch(marker, RpWaitAction.Leave, RpWaitReason.Called);
            if ((marker.Case is RpWaitCase.Siege or RpWaitCase.Warband) && musterOrder)
                return Latch(marker, RpWaitAction.Leave, RpWaitReason.Called);
            return RpWaitChange.Keep(marker);
        }

        if (!alive || !returning || !enabled || forThisDeath ||
            goal is not (eAutonomousObjectiveKind.RvR or eAutonomousObjectiveKind.Battleground))
            return RpWaitChange.Keep(marker);
        var released = new RpWaitMarker(deathCount, RpWaitPhase.Released, RpWaitCase.None, region, position, region,
            position, assignmentId, null, null, 0);
        return new RpWaitChange(marker, released, RpWaitAction.None, RpWaitReason.None);
    }

    // 3.7: a marker for an older death than deathCount: Waiting: Left, Leave(Died); Released: Left, action None.
    // Anything else: Keep.
    public static RpWaitChange Died(RpWaitMarker marker, int deathCount)
    {
        if (marker == null || marker.DeathCount >= deathCount)
            return RpWaitChange.Keep(marker);
        return marker.Phase switch
        {
            RpWaitPhase.Waiting => Latch(marker, RpWaitAction.Leave, RpWaitReason.Died),
            RpWaitPhase.Released => Latch(marker, RpWaitAction.None, RpWaitReason.None),
            _ => RpWaitChange.Keep(marker),
        };
    }

    // 3.8: with leaderIsPlayer, a marker for this death: Waiting: Left, Leave(PlayerGroup); Released: Left, action None.
    // Anything else: Keep.
    public static RpWaitChange JoinedGroup(RpWaitMarker marker, int deathCount, bool leaderIsPlayer)
    {
        if (!leaderIsPlayer || marker == null || marker.DeathCount != deathCount)
            return RpWaitChange.Keep(marker);
        return marker.Phase switch
        {
            RpWaitPhase.Waiting => Latch(marker, RpWaitAction.Leave, RpWaitReason.PlayerGroup),
            RpWaitPhase.Released => Latch(marker, RpWaitAction.None, RpWaitReason.None),
            _ => RpWaitChange.Keep(marker),
        };
    }

    // 2.4, 3.1-3.4: the spot a wait uses: a Waiting marker's Spot; for a Released marker, look.BattlegroundSlot in a
    // battleground (look.Case Battleground), else its ReleasePoint. Trips are measured from it. (A Left marker, which
    // no hook asks about, gives its stored Spot too.)
    public static Vector3 WaitSpot(RpWaitMarker marker, RpWaitLook look)
    {
        if (marker.Phase != RpWaitPhase.Released)
            return marker.Spot;
        return look.Case == RpWaitCase.Battleground ? look.BattlegroundSlot : marker.ReleasePoint;
    }

    // Decide's Ignore, Skip and Leave. Ignore keeps the marker read (the same reference: nothing to swap); a Skip
    // latches it Left with the hook's case stored, a Leave latches it Left; neither walks.
    private static RpWaitDecision Ignore(RpWaitMarker marker) =>
        new(RpWaitVerdict.Ignore, RpWaitReason.None, marker, marker, RpWaitAction.None, false);

    private static RpWaitDecision Skip(RpWaitMarker marker, RpWaitCase hookCase, RpWaitReason reason,
        RpWaitAction action = RpWaitAction.Skip) =>
        new(RpWaitVerdict.Skip, reason, marker, marker with { Phase = RpWaitPhase.Left, Case = hookCase }, action,
            false);

    private static RpWaitDecision Leave(RpWaitMarker marker, RpWaitReason reason) =>
        new(RpWaitVerdict.Leave, reason, marker, marker with { Phase = RpWaitPhase.Left }, RpWaitAction.Leave, false);

    // 2.3, 2.4, 3.1-3.4: hooks 1-2. The rules, in order (Left = marker with { Phase = Left }):
    // 1. marker null, or marker.DeathCount != deathCount: Ignore.
    // 2. Left: Ignore (the latch).
    // 3. Released (the first look):
    //    a. look.Case Warband: Ignore (the gate decides).
    //    b. timeLeft <= 0: Skip(Trip), Next = Left with Case = look.Case, action None (worth already: no line).
    //    c. look.Relic: Skip(Relic).
    //    d. Frontier or Siege with look.Region != marker.ReleaseRegion: Skip(OtherRegion).
    //    e. !look.HasTarget: Skip(NoTarget).  f. look.TargetRegion != look.Region: Skip(OtherRegion).
    //    g. outside the gate (Battleground: Distance2D(Position, Arrival) > 2,500; Frontier, Siege: Distance2D(Position,
    //       ReleasePoint) > 750): Skip(MovedAway).
    //    h. timeLeft <= trip: Skip(Trip).
    //    i. Start: marker with { Phase = Waiting, Case = look.Case, Region = look.Region, Spot = WaitSpot(marker, look),
    //       AssignmentId = look.AssignmentId, EventKeepId = look.Case == Siege ? look.EventKeepId : null, Started = now },
    //       action Start, WalkBack = Distance2D(Position, Spot) > SpotTolerance (48: it walks to its spot).
    //    Each Skip: Next = Left with Case = look.Case, action Skip.
    // 4. Waiting (each Leave: Next = Left, action Leave):
    //    a. look.AssignmentId != marker.AssignmentId: Leave(Changed).
    //    b. marker.Case Siege, look.Case Siege, look.EventKeepId != marker.EventKeepId: Leave(Called) (before the region).
    //    c. look.Region != marker.Region: Leave(Changed).
    //    d. look.Relic: Leave(Relic).
    //    e. marker.Case Warband: look.Case Warband: Ignore (the gate's); look.Case Siege: Distance2D(Position, Spot) > 200:
    //       Leave(MovedAway); !HasTarget: Leave(NoTarget); TargetRegion != Region: Leave(OtherRegion); timeLeft <= trip:
    //       Leave(Due); else Convert: marker with { Case = Siege, EventKeepId = look.EventKeepId, Started = now },
    //       Reason Battle, action Convert, WalkBack false; look.Case Frontier or Battleground: Leave(Changed).
    //    f. look.Case != marker.Case: Leave(Changed).
    //    g. !HasTarget: Leave(NoTarget); TargetRegion != Region: Leave(OtherRegion).
    //    h. timeLeft <= trip: Leave(Due).
    //    i. Hold: Next = marker, action None, WalkBack = Distance2D(Position, marker.Spot) > 200.
    public static RpWaitDecision Decide(RpWaitMarker marker, int deathCount, RpWaitLook look, long timeLeft,
        long tripMilliseconds, long now)
    {
        if (marker == null || marker.DeathCount != deathCount || marker.Phase == RpWaitPhase.Left)
            return Ignore(marker);

        if (marker.Phase == RpWaitPhase.Released)
        {
            if (look.Case == RpWaitCase.Warband)
                return Ignore(marker);
            if (timeLeft <= 0)
                return Skip(marker, look.Case, RpWaitReason.Trip, RpWaitAction.None);
            if (look.Relic)
                return Skip(marker, look.Case, RpWaitReason.Relic);
            if ((look.Case is RpWaitCase.Frontier or RpWaitCase.Siege) && look.Region != marker.ReleaseRegion)
                return Skip(marker, look.Case, RpWaitReason.OtherRegion);
            if (!look.HasTarget)
                return Skip(marker, look.Case, RpWaitReason.NoTarget);
            if (look.TargetRegion != look.Region)
                return Skip(marker, look.Case, RpWaitReason.OtherRegion);
            bool outside = look.Case == RpWaitCase.Battleground
                ? Distance2D(look.Position, look.Arrival) > ArrivalGate
                : Distance2D(look.Position, marker.ReleasePoint) > BindGate;
            if (outside)
                return Skip(marker, look.Case, RpWaitReason.MovedAway);
            if (timeLeft <= tripMilliseconds)
                return Skip(marker, look.Case, RpWaitReason.Trip);

            Vector3 spot = WaitSpot(marker, look);
            RpWaitMarker started = marker with
            {
                Phase = RpWaitPhase.Waiting,
                Case = look.Case,
                Region = look.Region,
                Spot = spot,
                AssignmentId = look.AssignmentId,
                EventKeepId = look.Case == RpWaitCase.Siege ? look.EventKeepId : null,
                Started = now,
            };
            return new RpWaitDecision(RpWaitVerdict.Start, RpWaitReason.None, marker, started, RpWaitAction.Start,
                Distance2D(look.Position, spot) > SpotTolerance);
        }

        if (look.AssignmentId != marker.AssignmentId)
            return Leave(marker, RpWaitReason.Changed);
        if (marker.Case == RpWaitCase.Siege && look.Case == RpWaitCase.Siege &&
            look.EventKeepId != marker.EventKeepId)
            return Leave(marker, RpWaitReason.Called);
        if (look.Region != marker.Region)
            return Leave(marker, RpWaitReason.Changed);
        if (look.Relic)
            return Leave(marker, RpWaitReason.Relic);

        // 4.e: a held warband outside battle is the gate's; drafted into a battle (a siege) it converts at its slot,
        // after the same target and time checks as any wait.
        bool converts = marker.Case == RpWaitCase.Warband;
        if (converts)
        {
            if (look.Case == RpWaitCase.Warband)
                return Ignore(marker);
            if (look.Case != RpWaitCase.Siege)
                return Leave(marker, RpWaitReason.Changed);
            if (Distance2D(look.Position, marker.Spot) > SlotGate)
                return Leave(marker, RpWaitReason.MovedAway);
        }
        else if (look.Case != marker.Case)
        {
            return Leave(marker, RpWaitReason.Changed);
        }

        if (!look.HasTarget)
            return Leave(marker, RpWaitReason.NoTarget);
        if (look.TargetRegion != look.Region)
            return Leave(marker, RpWaitReason.OtherRegion);
        if (timeLeft <= tripMilliseconds)
            return Leave(marker, RpWaitReason.Due);
        if (converts)
        {
            RpWaitMarker siege = marker with { Case = RpWaitCase.Siege, EventKeepId = look.EventKeepId, Started = now };
            return new RpWaitDecision(RpWaitVerdict.Convert, RpWaitReason.Battle, marker, siege, RpWaitAction.Convert,
                false);
        }
        return new RpWaitDecision(RpWaitVerdict.Hold, RpWaitReason.None, marker, marker, RpWaitAction.None,
            Distance2D(look.Position, marker.Spot) > WalkBackBeyond);
    }

    // 3.4: a member released for its current death: its marker Released or Waiting for its own DeathCount. Only such
    // a member holds the warband gate, and only its marker is the gate's to write; a member resurrected in the field
    // (no marker, or an older death's) and a Left marker are neither.
    private static bool ReleasedForItsDeath(RpWarbandMember member) =>
        member.Marker is { Phase: RpWaitPhase.Released or RpWaitPhase.Waiting } marker &&
        marker.DeathCount == member.DeathCount;

    // 3.4: the warband gate. The rules, in order:
    // 1. !enabled, kind != RvR, or forceCommitted: (Waits false, Writes false, 0, 0).
    // 2. relicCarrier: (false, true, 0, 0).
    // 3. The holder: the member whose marker is Released or Waiting for its own DeathCount, with the largest TimeLeft
    //    above 0. None (all worth, or only resurrected members): (false, true, 0, 0).
    // 4. The holder's Death is null, for another DeathCount, or in another region than rendezvousRegion:
    //    (false, true, 0, 0).
    // 5. march = TripMilliseconds(Distance2D(rendezvous, holder.Death.Position), the largest BestSpeed of all members);
    //    (holder.TimeLeft > march, true, march, holder.TimeLeft).
    public static RpWarbandGate WarbandWaits(bool enabled, eAutonomousObjectiveKind kind, bool forceCommitted,
        bool relicCarrier, ushort rendezvousRegion, Vector3 rendezvous, IReadOnlyList<RpWarbandMember> members)
    {
        if (!enabled || kind != eAutonomousObjectiveKind.RvR || forceCommitted)
            return new RpWarbandGate(false, false, 0, 0);
        var opens = new RpWarbandGate(false, true, 0, 0);
        if (relicCarrier)
            return opens;

        // The holder starts as no member (no marker, time left 0), so it is one only with time left above 0; the
        // first of equals holds.
        RpWarbandMember holder = default;
        double fastest = 0;
        foreach (RpWarbandMember member in members)
        {
            fastest = Math.Max(fastest, member.BestSpeed);
            if (ReleasedForItsDeath(member) && member.TimeLeft > holder.TimeLeft)
                holder = member;
        }

        RpDeathRecord death = holder.Death;
        if (holder.Marker == null || death == null || death.DeathCount != holder.DeathCount ||
            death.Region != rendezvousRegion)
            return opens;

        long march = TripMilliseconds(Distance2D(rendezvous, death.Position), fastest);
        return new RpWarbandGate(holder.TimeLeft > march, true, march, holder.TimeLeft);
    }

    // 3.4: one member's change (WarbandMarks). Holding turns a member's Released marker Waiting at its slot; opening
    // latches its Released or Waiting marker Left; anything else (no writes, no marker for its death, a Left marker) is
    // kept.
    private static RpWaitChange WarbandMark(RpWarbandGate gate, ushort rendezvousRegion, RpWarbandMember member,
        string sessionId, long now)
    {
        RpWaitMarker marker = member.Marker;
        if (!gate.Writes || !ReleasedForItsDeath(member))
            return RpWaitChange.Keep(marker);

        if (gate.Waits)
        {
            if (marker.Phase != RpWaitPhase.Released || member.Region != rendezvousRegion || member.TimeLeft <= 0)
                return RpWaitChange.Keep(marker);
            RpWaitMarker waiting = marker with
            {
                Phase = RpWaitPhase.Waiting,
                Case = RpWaitCase.Warband,
                Region = rendezvousRegion,
                Spot = member.Slot,
                AssignmentId = member.AssignmentId,
                SessionId = sessionId,
                EventKeepId = null,
                Started = now,
            };
            return new RpWaitChange(marker, waiting, RpWaitAction.Start, RpWaitReason.None);
        }

        if (marker.Phase == RpWaitPhase.Waiting)
            return Latch(marker, RpWaitAction.Leave, RpWaitReason.Due);
        return member.TimeLeft > 0
            ? Latch(marker, RpWaitAction.Skip, RpWaitReason.Trip)
            : Latch(marker, RpWaitAction.None, RpWaitReason.None);
    }

    // 3.4: each member's change, in member order. !gate.Writes: every member Keep. Holding (gate.Waits): a member whose
    // marker is Released for its DeathCount, with Region == rendezvousRegion and TimeLeft > 0, becomes marker with
    // { Phase = Waiting, Case = Warband, Region = rendezvousRegion, Spot = Slot, AssignmentId = member's, SessionId =
    // sessionId, EventKeepId = null, Started = now }, action Start; every other member Keep. Opening (!gate.Waits): a
    // marker Waiting for its DeathCount: Left, Leave(Due); Released for its DeathCount: Left, Skip(Trip) when TimeLeft
    // > 0, else action None; every other member (no marker, Left, an older death) Keep.
    public static RpWaitChange[] WarbandMarks(RpWarbandGate gate, ushort rendezvousRegion,
        IReadOnlyList<RpWarbandMember> members, string sessionId, long now)
    {
        var changes = new RpWaitChange[members.Count];
        for (int i = 0; i < changes.Length; i++)
            changes[i] = WarbandMark(gate, rendezvousRegion, members[i], sessionId, now);
        return changes;
    }
}

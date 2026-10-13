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

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
}

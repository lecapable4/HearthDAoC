using System;
using System.Numerics;
using DOL.AI.Brain;
using DOL.Database;
using DOL.GS.HearthDAoC;
using DOL.GS.Keeps;
using DOL.GS.ServerProperties;

namespace DOL.GS;

// HearthDAoC: the controller side of the realm point timer waits (spec
// docs/fork/specs/2026-10-13-rp-timer-waits-design.md, 7.3): hook 1 (ExecuteBattleground) and hook 2 (ExecuteRvr)
// call these. They gather the inputs, ask RpTimerWait.Decide, then act: move, status, siege job, route reset, think
// wake, _nextRvrPlanReview. A fork part of the controller because they need its private members: IssuePath,
// SetStatus, SetBattlegroundStatus, ResetRouteOrderState, ReleaseSiegeJob (and its clearing of _siegeJobKeep,
// Siege.cs:469), _keepStallSince, _rvrDestination and _nextRvrPlanReview (deploy/tests/test_rp_timer_wait.py checks
// they still exist upstream).
public sealed partial class AutonomousWorldBotController
{
    private const string RpWaitActivity = "Waiting out the realm point timer";

    // Hook 1 (3.1); true holds the bot this turn. The slot's marker first (none, for another death count, or Left:
    // false), then the switch (off: false). now = GameLoop.GameLoopTime. Look: Case Battleground; Region, Position,
    // AssignmentId now; EventKeepId null; Relic false; target = RpTimerWait.FirstContactPoint(BotArrival(bracket,
    // bot.Realm) XY, central XY) at the arrival's Z, in bracket.RegionId (central null: no target); Arrival = BotArrival;
    // BattlegroundSlot, only for a Released marker, = AutonomousTownTeleporters.Arrival(new DbTeleport { RegionID =
    // bracket.RegionId, X, Y, Z of BotArrival }, 1 + bot.ObjectID % 12). tripKnown = target known (same region);
    // trip = tripKnown ? RpTimerWait.TripMilliseconds(RpTimerWait.Distance2D(RpTimerWait.WaitSpot(marker, look), target),
    // RpTimerWaitScript.BestSpeed(bot)) : long.MaxValue. Then RpWaitAct(..., bracket).
    private bool RpTimerWaitBattleground(BotBrain brain, GameBot bot, BattlegroundBrackets.Bracket bracket,
        AbstractGameKeep central)
    {
        RpWaitSlot slot = RpTimerWaitScript.SlotOf(bot);
        RpWaitMarker marker = slot?.Current;
        if (marker == null || bot.PersistentRecord is not { } record || marker.DeathCount != record.DeathCount ||
            marker.Phase == RpWaitPhase.Left || !RpTimerWaitScript.BOT_RP_TIMER_WAIT)
            return false;
        // Every realm a bot can have has an arrival point (BattlegroundBrackets.cs:95-101).
        if (BattlegroundBrackets.BotArrival(bracket, bot.Realm) is not { } arrival)
            return false;

        long now = GameLoop.GameLoopTime;
        Vector3 arrivalPoint = new(arrival.X, arrival.Y, arrival.Z);
        bool hasTarget = central != null;
        Vector3 target = Vector3.Zero;
        if (hasTarget)
        {
            Vector2 contact = RpTimerWait.FirstContactPoint(new(arrival.X, arrival.Y), new(central.X, central.Y));
            target = new(contact.X, contact.Y, arrival.Z);
        }
        // The slot is navmesh-snapped: asked only at the first look, which stores it as the wait's spot.
        Vector3 battlegroundSlot = marker.Phase == RpWaitPhase.Released
            ? AutonomousTownTeleporters.Arrival(new DbTeleport
                { RegionID = bracket.RegionId, X = arrival.X, Y = arrival.Y, Z = arrival.Z }, 1 + bot.ObjectID % 12)
            : Vector3.Zero;
        var look = new RpWaitLook(RpWaitCase.Battleground, bot.CurrentRegionID, new(bot.X, bot.Y, bot.Z),
            record.ObjectiveAssignmentId, null, false, hasTarget, bracket.RegionId, arrivalPoint, battlegroundSlot);
        bool tripKnown = hasTarget && look.TargetRegion == look.Region;
        long timeLeft = RpTimerWaitScript.WorthlessFor(bot);
        long trip = tripKnown
            ? RpTimerWait.TripMilliseconds(RpTimerWait.Distance2D(RpTimerWait.WaitSpot(marker, look), target),
                RpTimerWaitScript.BestSpeed(bot))
            : long.MaxValue;
        RpWaitDecision decision = RpTimerWait.Decide(marker, record.DeathCount, look, timeLeft, trip, now);
        return RpWaitAct(brain, bot, slot, decision, timeLeft, trip, tripKnown, now, bracket);
    }

    // Hook 2 (3.2, 3.3); true holds the bot this turn. The slot's marker first, then the switch, as hook 1. Look: Case =
    // battleActive && keepPlan ? Siege : dynamicWarband && !battleActive ? Warband : Frontier; Relic =
    // GameRelic.IsPlayerCarryingRelic(bot) || _rvrDestination?.Id starts with "rvr-relic-carrier-" (ordinal) ||
    // (battleActive && !keepPlan); EventKeepId = Siege ? _rvrDestination?.Id : null; target: Siege, _rvrDestination
    // (null: none); Frontier, RpWaitFrontierTarget; Warband, none. Trip as hook 1. Then RpWaitAct(..., null).
    private bool RpTimerWaitRvr(BotBrain brain, GameBot bot, bool battleActive, bool dynamicWarband, bool keepPlan)
    {
        RpWaitSlot slot = RpTimerWaitScript.SlotOf(bot);
        RpWaitMarker marker = slot?.Current;
        if (marker == null || bot.PersistentRecord is not { } record || marker.DeathCount != record.DeathCount ||
            marker.Phase == RpWaitPhase.Left || !RpTimerWaitScript.BOT_RP_TIMER_WAIT)
            return false;

        long now = GameLoop.GameLoopTime;
        RpWaitCase hookCase = battleActive && keepPlan ? RpWaitCase.Siege
            : dynamicWarband && !battleActive ? RpWaitCase.Warband
            : RpWaitCase.Frontier;
        CampDestination destination = _rvrDestination;
        bool relic = GameRelic.IsPlayerCarryingRelic(bot) ||
            destination?.Id?.StartsWith("rvr-relic-carrier-", StringComparison.Ordinal) == true ||
            (battleActive && !keepPlan);
        (bool Known, ushort Region, Vector3 Point) target = hookCase switch
        {
            RpWaitCase.Siege when destination != null =>
                (true, destination.RegionId, new Vector3(destination.X, destination.Y, destination.Z)),
            RpWaitCase.Frontier => RpWaitFrontierTarget(bot, record.DeathCount),
            _ => (false, 0, Vector3.Zero),
        };
        var look = new RpWaitLook(hookCase, bot.CurrentRegionID, new(bot.X, bot.Y, bot.Z), record.ObjectiveAssignmentId,
            hookCase == RpWaitCase.Siege ? destination?.Id : null, relic, target.Known, target.Region, Vector3.Zero,
            Vector3.Zero);
        bool tripKnown = target.Known && target.Region == look.Region;
        long timeLeft = RpTimerWaitScript.WorthlessFor(bot);
        long trip = tripKnown
            ? RpTimerWait.TripMilliseconds(RpTimerWait.Distance2D(RpTimerWait.WaitSpot(marker, look), target.Point),
                RpTimerWaitScript.BestSpeed(bot))
            : long.MaxValue;
        RpWaitDecision decision = RpTimerWait.Decide(marker, record.DeathCount, look, timeLeft, trip, now);
        return RpWaitAct(brain, bot, slot, decision, timeLeft, trip, tripKnown, now, null);
    }

    // 3.2: a frontier solo's trip target. _rvrDestination when its RegionId is the bot's region; else the death record
    // for deathCount when its Region is the bot's; else _rvrDestination in its own region, else that death record in its
    // own region (both other-region); else none (no-target).
    private (bool Known, ushort Region, Vector3 Point) RpWaitFrontierTarget(GameBot bot, int deathCount)
    {
        CampDestination destination = _rvrDestination;
        RpDeathRecord death = RpTimerWaitScript.DeathRecordOf(bot);
        if (death != null && death.DeathCount != deathCount)
            death = null;
        ushort region = bot.CurrentRegionID;
        if (destination != null && destination.RegionId == region)
            return (true, region, new Vector3(destination.X, destination.Y, destination.Z));
        if (death != null && death.Region == region)
            return (true, region, death.Position);
        if (destination != null)
            return (true, destination.RegionId, new Vector3(destination.X, destination.Y, destination.Z));
        if (death != null)
            return (true, death.Region, death.Position);
        return (false, 0, Vector3.Zero);
    }

    // Section 4: carries out one decision; returns the hook's value. tripKnown false: the log's trip is "-".
    // Ignore: false.
    // Skip, Leave: slot.TrySwap(decision.Before, decision.Next) (lost: false); Skip with action Skip: WriteSkip(Next.Case);
    //   Leave: WriteLeave(Before); Leave also ResetRouteOrderState() and _keepStallSince = 0; a Frontier Skip(Trip) or
    //   Leave(Due) with timeLeft > 0 sets _nextRvrPlanReview = Math.Max(_nextRvrPlanReview, now + timeLeft). false: the
    //   bot goes on this turn.
    // Start, Convert and Hold first compute leaveTick = RpTimerWait.LeaveTick(RpTimerWaitScript.RealmPointDeathTick(bot),
    //   Properties.RP_WORTH_SECONDS, tripMilliseconds).
    // Start, Convert: swap (lost: false); Convert first WriteLeave(Before, reason Battle); WriteStart(Next, timeLeft, trip,
    //   leaveTick - now); bot.StopMovingOnPath(); bot.StopMoving(); ReleaseSiegeJob(bot); ResetRouteOrderState();
    //   _keepStallSince = 0; then as Hold.
    // Hold: IssuePath(bot, Next.Spot) when decision.WalkBack, or when bot.IsMovingOnPath and RpTimerWait.Distance2D(the
    //   bot's position, Next.Spot) > RpTimerWait.SpotTolerance (the walk to the spot goes on: IssuePath keeps a running
    //   order to the same destination, WBC:4276-4278, and stops the bot within 48 of it, WBC:4144-4150); else stop
    //   (StopMovingOnPath, StopMoving) if IsMoving or IsMovingOnPath; status, progress $"Worth realm points in
    //   {Seconds(timeLeft)} s; leaving in {Seconds(max(0, timeLeft - trip))} s": bracket != null ?
    //   SetBattlegroundStatus(bot, bracket, RpWaitActivity,
    //   progress) : (PersistentRecord.ObjectivePhase = RpWaitActivity; SetStatus(bot, RpWaitActivity, "Active frontier
    //   RvR", progress, "", _rvrDestination?.ZoneName ?? "")), never a forced save; think wake brain.ThinkInterval =
    //   RpTimerWait.ThinkWakeMilliseconds(leaveTick, now, GameLoop.TickDuration, brain.ThinkInterval); true.
    private bool RpWaitAct(BotBrain brain, GameBot bot, RpWaitSlot slot, RpWaitDecision decision, long timeLeft,
        long tripMilliseconds, bool tripKnown, long now, BattlegroundBrackets.Bracket bracket)
    {
        long loggedTrip = tripKnown ? tripMilliseconds : -1;
        switch (decision.Verdict)
        {
            case RpWaitVerdict.Ignore:
                return false;
            case RpWaitVerdict.Skip:
            case RpWaitVerdict.Leave:
                // A lost swap writes and logs nothing: the next turn decides again.
                if (!slot.TrySwap(decision.Before, decision.Next))
                    return false;
                if (decision.Action == RpWaitAction.Skip)
                    RpTimerWaitScript.WriteSkip(bot, decision.Next.Case, timeLeft, decision.Reason);
                if (decision.Verdict == RpWaitVerdict.Leave)
                {
                    RpTimerWaitScript.WriteLeave(bot, decision.Before, now, timeLeft, loggedTrip, decision.Reason);
                    ResetRouteOrderState();
                    _keepStallSince = 0;
                }
                // 3.2: a frontier solo leaving at its moment keeps its destination until it is worth points again,
                // rather than re-picking a nearer one at once and arriving early.
                bool leavesOnTime = (decision.Verdict == RpWaitVerdict.Skip && decision.Reason == RpWaitReason.Trip) ||
                    (decision.Verdict == RpWaitVerdict.Leave && decision.Reason == RpWaitReason.Due);
                if (decision.Next.Case == RpWaitCase.Frontier && leavesOnTime && timeLeft > 0)
                    _nextRvrPlanReview = Math.Max(_nextRvrPlanReview, now + timeLeft);
                return false;
        }

        long leaveTick = RpTimerWait.LeaveTick(RpTimerWaitScript.RealmPointDeathTick(bot), Properties.RP_WORTH_SECONDS,
            tripMilliseconds);
        if (decision.Verdict is RpWaitVerdict.Start or RpWaitVerdict.Convert)
        {
            if (!slot.TrySwap(decision.Before, decision.Next))
                return false;
            if (decision.Verdict == RpWaitVerdict.Convert)
                RpTimerWaitScript.WriteLeave(bot, decision.Before, now, timeLeft, loggedTrip, RpWaitReason.Battle);
            RpTimerWaitScript.WriteStart(bot, decision.Next, timeLeft, tripMilliseconds, leaveTick - now);
            bot.StopMovingOnPath();
            bot.StopMoving();
            ReleaseSiegeJob(bot);
            ResetRouteOrderState();
            _keepStallSince = 0;
        }

        Vector3 spot = decision.Next.Spot;
        if (decision.WalkBack ||
            bot.IsMovingOnPath && RpTimerWait.Distance2D(new(bot.X, bot.Y, bot.Z), spot) > RpTimerWait.SpotTolerance)
        {
            IssuePath(bot, spot);
        }
        else if (bot.IsMoving || bot.IsMovingOnPath)
        {
            bot.StopMovingOnPath();
            bot.StopMoving();
        }

        string progress = $"Worth realm points in {RpTimerWaitScript.Seconds(timeLeft)} s; leaving in " +
            $"{RpTimerWaitScript.Seconds(Math.Max(0, timeLeft - tripMilliseconds))} s";
        if (bracket != null)
        {
            SetBattlegroundStatus(bot, bracket, RpWaitActivity, progress);
        }
        else
        {
            if (bot.PersistentRecord is { } record)
                record.ObjectivePhase = RpWaitActivity;
            SetStatus(bot, RpWaitActivity, "Active frontier RvR", progress, "", _rvrDestination?.ZoneName ?? "");
        }
        brain.ThinkInterval = RpTimerWait.ThinkWakeMilliseconds(leaveTick, now, GameLoop.TickDuration,
            brain.ThinkInterval);
        return true;
    }
}

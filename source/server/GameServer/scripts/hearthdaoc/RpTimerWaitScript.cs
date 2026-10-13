using System;
using System.Globalization;
using System.Numerics;
using DOL.Events;
using DOL.GS.ServerProperties;
using DOL.Logging;

namespace DOL.GS.HearthDAoC;

// HearthDAoC: the game wiring of the realm point timer waits (spec docs/fork/specs/2026-10-13-rp-timer-waits-design.md,
// 7.2). RpTimerWait makes every decision; this class reads the bot's state, swaps the markers, registers the death and
// group handlers, and writes the HEARTHDAOC_RP_WAIT log. Off by default; HearthDAoC turns it on through
// HEARTHDAOC_BOT_RP_TIMER_WAIT.
public static class RpTimerWaitScript
{
    [ServerProperty("server", "bot_rp_timer_wait",
        "Released gamebots wait at a safe spot until their trip back to the fight ends as their rp_worth_seconds timer does, so they come back worth realm points",
        false)]
    public static bool BOT_RP_TIMER_WAIT;

    /// <summary>The TempProperty holding the bot's <see cref="RpWaitSlot"/> (7.2).</summary>
    public const string WaitKey = "hearthdaoc.rp.wait";
    /// <summary>The TempProperty holding the bot's last <see cref="RpDeathRecord"/> (3.7).</summary>
    public const string DeathKey = "hearthdaoc.rp.death";
    /// <summary>Every log line starts with this (10.5).</summary>
    public const string LogPrefix = "HEARTHDAOC_RP_WAIT";

    private static readonly Logger Log = LoggerManager.Create(typeof(RpTimerWaitScript));

    // 7.2: the bot's slot (TempProperty WaitKey), or null: one dictionary read.
    public static RpWaitSlot SlotOf(GameBot bot) => bot.TempProperties.GetProperty<RpWaitSlot>(WaitKey);

    // 3.7: the bot's last death record (TempProperty DeathKey), or null.
    public static RpDeathRecord DeathRecordOf(GameBot bot) => bot.TempProperties.GetProperty<RpDeathRecord>(DeathKey);

    // 2.1: the realm point timer, read through AutonomousBotRealmPointRewards.LastRealmPointDeathTickProperty (internal,
    // same assembly), -1 when none.
    public static long RealmPointDeathTick(GameBot bot) =>
        bot.TempProperties.GetProperty<long>(AutonomousBotRealmPointRewards.LastRealmPointDeathTickProperty, -1);

    // 2.1, 7.2: RpTimerWait.WorthlessForMilliseconds(RealmPointDeathTick(bot), GameLoop.GameLoopTime,
    // Properties.RP_WORTH_SECONDS).
    public static long WorthlessFor(GameBot bot) =>
        RpTimerWait.WorthlessForMilliseconds(RealmPointDeathTick(bot), GameLoop.GameLoopTime, Properties.RP_WORTH_SECONDS);

    // 2.2: RpTimerWait.BestSpeed(bot.MaxSpeed, bot.MaxSpeedBase, v), v the largest Value of a spell with SpellType
    // eSpellType.SpeedEnhancement, IsPulsing, !IsHarmful and Level <= bot.Level: the song upkeep's own pool and filter
    // (BB:2177-2181). It reads snapshots, bot.MiscSpells?.ToArray() and bot.InstantMiscSpells?.ToArray() (either list
    // may be null; another thread may rebuild them, GameBot.SortSpells clearing and refilling them in place, GB:1878-1890),
    // skipping null entries; 0 when none.
    public static double BestSpeed(GameBot bot)
    {
        int level = bot.Level;
        double song = Math.Max(BestSpeedSong(bot.MiscSpells?.ToArray(), level),
            BestSpeedSong(bot.InstantMiscSpells?.ToArray(), level));
        return RpTimerWait.BestSpeed(bot.MaxSpeed, bot.MaxSpeedBase, song);

        static double BestSpeedSong(Spell[] spells, int level)
        {
            double best = 0;
            foreach (Spell spell in spells ?? [])
            {
                if (spell is { SpellType: eSpellType.SpeedEnhancement, IsPulsing: true, IsHarmful: false } &&
                    spell.Level <= level && spell.Value > best)
                    best = spell.Value;
            }
            return best;
        }
    }

    // 3.5, hook 3 (every controller turn of a gamebot that is not player-led). Reads the slot's marker and
    // IsReturningAfterRelease, and returns at once when it has neither. Reads the event layer only for a marker Waiting for
    // this death, with the switch on and the same assignment id and region (Frontier: IsForceCommitted(force); Siege,
    // Warband: GetRallyOrder(force, realm, now) != null; force = the marker's SessionId for a Warband marker, else the
    // bot's "RvrEventForce" TempProperty, else rvr-<DatabaseID>). Asks RpTimerWait.Note; creates the slot
    // (TempProperties.TrySetProperty, then SlotOf) only to write a first marker; swaps against the marker read; after a
    // successful swap writes a leave line (trip unknown) when the change's action is Leave.
    public static void NoteRelease(GameBot bot)
    {
        RpWaitSlot slot = SlotOf(bot);
        RpWaitMarker marker = slot?.Current;
        bool returning = bot.IsReturningAfterRelease;
        if (marker == null && !returning)
            return;
        OfflineWorldBotRecord record = bot.PersistentRecord;
        if (record == null)
            return;

        bool enabled = BOT_RP_TIMER_WAIT;
        int deathCount = record.DeathCount;
        ushort region = bot.CurrentRegionID;
        string assignmentId = record.ObjectiveAssignmentId;
        long now = GameLoop.GameLoopTime;
        bool forceCommitted = false, musterOrder = false;
        if (enabled && marker is { Phase: RpWaitPhase.Waiting } && marker.DeathCount == deathCount &&
            marker.AssignmentId == assignmentId && marker.Region == region)
        {
            // The force as ExecuteRvr records it (WBC:1695-1696) and AutonomousFrontierTransport.cs:86 reads it.
            string force = (marker.Case == RpWaitCase.Warband ? marker.SessionId : null) ??
                bot.TempProperties.GetProperty<string>("RvrEventForce") ?? $"rvr-{bot.DatabaseID}";
            if (marker.Case == RpWaitCase.Frontier)
                forceCommitted = AutonomousRvrEventLayer.IsForceCommitted(force, now);
            else if (marker.Case is RpWaitCase.Siege or RpWaitCase.Warband)
                musterOrder = AutonomousRvrEventLayer.GetRallyOrder(force, bot.Realm, now) != null;
        }

        RpWaitChange change = RpTimerWait.Note(enabled, marker, deathCount, bot.IsAlive, returning,
            AutonomousObjectiveAssignments.KindFor(bot), region, new Vector3(bot.X, bot.Y, bot.Z), assignmentId,
            bot.Group != null, forceCommitted, musterOrder);
        if (!change.Changes)
            return;
        if (slot == null)
        {
            bot.TempProperties.TrySetProperty(WaitKey, new RpWaitSlot());
            slot = SlotOf(bot);
        }
        // A lost swap writes and logs nothing: the next turn decides again.
        if (slot.TrySwap(marker, change.Next) && change.Action == RpWaitAction.Leave)
            WriteLeave(bot, marker, now, WorthlessFor(bot), -1, change.Reason);
    }

    // 2.4, hooks 5 and 6: the marker first (none: false), then the switch (off: false), then RpTimerWait.IsWaiting with
    // the bot's death count (no PersistentRecord: false), WorthlessFor, region, position, assignment id,
    // IsPlayerLedGroup, Group != null, and its realm's BattlegroundBrackets.BotArrival only for a Released marker in a
    // battleground region (else null). No clock, no IsSafeArea, no lock but the TempProperties read.
    public static bool IsWaiting(GameBot bot)
    {
        RpWaitMarker marker = SlotOf(bot)?.Current;
        if (marker == null || !BOT_RP_TIMER_WAIT || bot.PersistentRecord is not { } record)
            return false;

        ushort region = bot.CurrentRegionID;
        Vector3? arrival = null;
        if (marker.Phase == RpWaitPhase.Released && RpTimerWait.IsBattlegroundRegion(region) &&
            BattlegroundBrackets.ForRegion(region) is { } bracket &&
            BattlegroundBrackets.BotArrival(bracket, bot.Realm) is { } location)
            arrival = new Vector3(location.X, location.Y, location.Z);
        // The switch is on: read above.
        return RpTimerWait.IsWaiting(true, marker, record.DeathCount, WorthlessFor(bot), region,
            new Vector3(bot.X, bot.Y, bot.Z), record.ObjectiveAssignmentId, bot.IsPlayerLedGroup, bot.Group != null,
            arrival);
    }

    // 3.4, hook 4, under the coordinator lock (GC:212). Returns false at once, with no writes, unless some member's
    // marker is Released or Waiting for that member's current PersistentRecord.DeathCount (one marker read per member;
    // a member with no PersistentRecord has none). That is the same result: with no such member WarbandWaits gives
    // (false, true, 0, 0) and WarbandMarks keeps every marker. Then false at once when the switch is off or
    // objectiveKind is not RvR; reads AutonomousRvrEventLayer.IsForceCommitted(sessionId, now) once (true: false, no
    // writes). Builds each member's RpWarbandMember; Slot = AutonomousBotGroupCoordinator.RendezvousFormationPoint(member,
    // sessionId, rendezvous, member in a dungeon region or zone) (the re-entrant lock) only for a member whose marker is
    // Released for its death, with time left > 0, in rendezvousRegion (the only member WarbandMarks can turn Waiting);
    // every other member gets Slot = rendezvous. Relic carrier = any member with GameRelic.IsPlayerCarryingRelic; asks
    // RpTimerWait.WarbandWaits, then WarbandMarks; swaps each change against the marker read and, after a successful
    // swap only, logs: Start: start line (trip = MarchMilliseconds, leaveIn = HolderTimeLeft - MarchMilliseconds); Leave:
    // leave line (reason due, trip = MarchMilliseconds; "-" when no member holds the gate, so no march was measured);
    // Skip: skip line (case warband, reason trip). A lost swap logs nothing. Returns gate.Waits.
    public static bool WarbandWaits(string sessionId, eAutonomousObjectiveKind objectiveKind, ushort rendezvousRegion,
        Vector3 rendezvous, GameBot[] members)
    {
        var slots = new RpWaitSlot[members.Length];
        var markers = new RpWaitMarker[members.Length];
        bool anyReleased = false;
        for (int i = 0; i < members.Length; i++)
        {
            if (members[i].PersistentRecord is not { } record)
                continue;
            slots[i] = SlotOf(members[i]);
            markers[i] = slots[i]?.Current;
            anyReleased |= markers[i] is { Phase: RpWaitPhase.Released or RpWaitPhase.Waiting } marker &&
                marker.DeathCount == record.DeathCount;
        }
        if (!anyReleased || !BOT_RP_TIMER_WAIT || objectiveKind != eAutonomousObjectiveKind.RvR)
            return false;
        long now = GameLoop.GameLoopTime;
        if (AutonomousRvrEventLayer.IsForceCommitted(sessionId, now))
            return false;

        var view = new RpWarbandMember[members.Length];
        bool relicCarrier = false;
        for (int i = 0; i < members.Length; i++)
        {
            GameBot member = members[i];
            OfflineWorldBotRecord record = member.PersistentRecord;
            int deathCount = record?.DeathCount ?? 0;
            long timeLeft = WorthlessFor(member);
            ushort region = member.CurrentRegionID;
            bool turnsWaiting = markers[i] is { Phase: RpWaitPhase.Released } marker &&
                marker.DeathCount == deathCount && timeLeft > 0 && region == rendezvousRegion;
            Vector3 slot = turnsWaiting
                ? AutonomousBotGroupCoordinator.RendezvousFormationPoint(member, sessionId, rendezvous,
                    member.CurrentRegion?.IsDungeon == true || member.CurrentZone?.IsDungeon == true)
                : rendezvous;
            view[i] = new RpWarbandMember(markers[i], deathCount, timeLeft, DeathRecordOf(member), region, slot,
                record?.ObjectiveAssignmentId, BestSpeed(member));
            relicCarrier |= GameRelic.IsPlayerCarryingRelic(member);
        }

        // The switch is on, the session RvR and its force not committed: read above.
        RpWarbandGate gate = RpTimerWait.WarbandWaits(true, objectiveKind, false, relicCarrier, rendezvousRegion,
            rendezvous, view);
        RpWaitChange[] changes = RpTimerWait.WarbandMarks(gate, rendezvousRegion, view, sessionId, now);
        long march = gate.HolderTimeLeft > 0 ? gate.MarchMilliseconds : -1;
        for (int i = 0; i < changes.Length; i++)
        {
            RpWaitChange change = changes[i];
            // A change has a marker, so the member has a slot. A lost swap logs nothing: the next pass decides again.
            if (!change.Changes || !slots[i].TrySwap(change.Before, change.Next))
                continue;
            long timeLeft = view[i].TimeLeft;
            switch (change.Action)
            {
                case RpWaitAction.Start:
                    WriteStart(members[i], change.Next, timeLeft, gate.MarchMilliseconds,
                        gate.HolderTimeLeft - gate.MarchMilliseconds);
                    break;
                case RpWaitAction.Leave:
                    WriteLeave(members[i], change.Before, now, timeLeft, march, change.Reason);
                    break;
                case RpWaitAction.Skip:
                    WriteSkip(members[i], RpWaitCase.Warband, timeLeft, change.Reason);
                    break;
            }
        }
        return gate.Waits;
    }

    [ScriptLoadedEvent]
    public static void OnScriptLoaded(DOLEvent e, object sender, EventArgs args)
    {
        GameEventMgr.AddHandler(GameLivingEvent.Dying, OnDying);
        GameEventMgr.AddHandler(GroupEvent.MemberJoined, OnMemberJoined);
    }

    [ScriptUnloadedEvent]
    public static void OnScriptUnloaded(DOLEvent e, object sender, EventArgs args)
    {
        GameEventMgr.RemoveHandler(GameLivingEvent.Dying, OnDying);
        GameEventMgr.RemoveHandler(GroupEvent.MemberJoined, OnMemberJoined);
    }

    // 3.7, every living's death; leaves at once for anything but a GameBot with IsAutonomousWorldBot, not
    // IsTemporaryGroupHelper, with a PersistentRecord. With the switch on or off: previous = DeathRecordOf(bot); writes
    // new RpDeathRecord(DeathCount, CurrentRegionID, position, now, RealmPointDeathTick(bot)); when the killer
    // ((args as DyingEventArgs)?.Killer as GameLiving, through AutonomousBotRealmPointRewards.ResolveRootRewardOwner) is
    // of a realm other than None and the bot's, writes the died line: worth = previous == null ||
    // RpTimerWait.WorthlessForMilliseconds(previous.TimerValue, now, RP_WORTH_SECONDS) == 0; sinceLastDeath = previous
    // == null || previous.TimerValue < 0 ? -1 : now - previous.TimerValue. Then, with a slot, slot.Apply(m =>
    // RpTimerWait.Died(m, DeathCount)) and a leave line (reason died, trip unknown) when its action is Leave. Catches
    // and logs any exception: a handler must never break a death.
    private static void OnDying(DOLEvent e, object sender, EventArgs args)
    {
        if (sender is not GameBot { IsAutonomousWorldBot: true, IsTemporaryGroupHelper: false } bot ||
            bot.PersistentRecord is not { } record)
            return;
        try
        {
            // Dying fires as the death ends (GameLiving.cs:2073): the death count (GB:953) and the timer (ARPR:90)
            // are written.
            long now = GameLoop.GameLoopTime;
            int deathCount = record.DeathCount;
            RpDeathRecord previous = DeathRecordOf(bot);
            bot.TempProperties.SetProperty(DeathKey, new RpDeathRecord(deathCount, bot.CurrentRegionID,
                new Vector3(bot.X, bot.Y, bot.Z), now, RealmPointDeathTick(bot)));

            // RVR_BOT_KILLED's filter (ARPR:66-68). worth is what ARPR:86 read for this death: the timer as the
            // previous death left it.
            if (Log.IsInfoEnabled && (args as DyingEventArgs)?.Killer is GameLiving killer)
            {
                GameLiving owner = AutonomousBotRealmPointRewards.ResolveRootRewardOwner(killer) ?? killer;
                if (owner.Realm != eRealm.None && owner.Realm != bot.Realm)
                {
                    bool worth = previous == null || RpTimerWait.WorthlessForMilliseconds(previous.TimerValue, now,
                        Properties.RP_WORTH_SECONDS) == 0;
                    long sinceLastDeath = previous == null || previous.TimerValue < 0 ? -1 : now - previous.TimerValue;
                    Log.Info(DiedLine(bot.Name, bot.DatabaseID, bot.Realm, AutonomousObjectiveAssignments.KindFor(bot),
                        owner.Realm, worth, sinceLastDeath, bot.CurrentRegionID, bot.X, bot.Y, bot.Z));
                }
            }

            RpWaitSlot slot = SlotOf(bot);
            if (slot == null)
                return;
            // No next turn for a handler: Apply retries a lost swap.
            RpWaitChange change = slot.Apply(marker => RpTimerWait.Died(marker, deathCount));
            if (change.Action == RpWaitAction.Leave)
                WriteLeave(bot, change.Before, now, WorthlessFor(bot), -1, change.Reason);
        }
        catch (Exception ex)
        {
            Log.Error($"{LogPrefix}: could not record the death of {bot.Name}", ex);
        }
    }

    // 3.8: sender is the Group, args a MemberJoinedEventArgs whose Member is a GameBot with a slot and a
    // PersistentRecord. leaderIsPlayer = group.LivingLeader is GamePlayer. slot.Apply(m => RpTimerWait.JoinedGroup(m,
    // DeathCount, leaderIsPlayer)); a leave line (reason player-group, trip unknown) when its action is Leave. Catches
    // and logs any exception.
    private static void OnMemberJoined(DOLEvent e, object sender, EventArgs args)
    {
        if (sender is not Group group || (args as MemberJoinedEventArgs)?.Member is not GameBot bot)
            return;
        try
        {
            RpWaitSlot slot = SlotOf(bot);
            if (slot == null || bot.PersistentRecord is not { } record)
                return;
            int deathCount = record.DeathCount;
            bool leaderIsPlayer = group.LivingLeader is GamePlayer;
            // No next turn for a handler: Apply retries a lost swap.
            RpWaitChange change = slot.Apply(marker => RpTimerWait.JoinedGroup(marker, deathCount, leaderIsPlayer));
            if (change.Action == RpWaitAction.Leave)
                WriteLeave(bot, change.Before, GameLoop.GameLoopTime, WorthlessFor(bot), -1, change.Reason);
        }
        catch (Exception ex)
        {
            Log.Error($"{LogPrefix}: could not end the wait of {bot.Name} at a group join", ex);
        }
    }

    // 10.5: none, battleground, frontier, siege, warband.
    public static string CaseWord(RpWaitCase value) => value switch
    {
        RpWaitCase.None => "none",
        RpWaitCase.Battleground => "battleground",
        RpWaitCase.Frontier => "frontier",
        RpWaitCase.Siege => "siege",
        RpWaitCase.Warband => "warband",
        _ => value.ToString(),
    };

    // 10.5: "" (None), trip, other-region, moved-away, relic, no-target, due, off, changed, called, player-group,
    // battle, died.
    public static string ReasonWord(RpWaitReason value) => value switch
    {
        RpWaitReason.None => "",
        RpWaitReason.Trip => "trip",
        RpWaitReason.OtherRegion => "other-region",
        RpWaitReason.MovedAway => "moved-away",
        RpWaitReason.Relic => "relic",
        RpWaitReason.NoTarget => "no-target",
        RpWaitReason.Due => "due",
        RpWaitReason.Off => "off",
        RpWaitReason.Changed => "changed",
        RpWaitReason.Called => "called",
        RpWaitReason.PlayerGroup => "player-group",
        RpWaitReason.Battle => "battle",
        RpWaitReason.Died => "died",
        _ => value.ToString(),
    };

    // 10.5: whole seconds rounded to the nearest, (ms + 500) / 1000; "-" for a negative value (unknown); "never" for
    // long.MaxValue (no speed). Computed without the + 500, which would overflow just below long.MaxValue.
    public static string Seconds(long milliseconds) => milliseconds switch
    {
        long.MaxValue => "never",
        < 0 => "-",
        _ => (milliseconds / 1000 + (milliseconds % 1000 >= 500 ? 1 : 0)).ToString(CultureInfo.InvariantCulture),
    };

    // 10.5: "HEARTHDAOC_RP_WAIT action=died bot=<name> id=<id> realm=<RealmToName> goal=<goal> killerRealm=<RealmToName>
    // worth=<yes|no> sinceLastDeath=<Seconds, or none when negative> region=<region> position=<x>,<y>,<z>"
    // The four lines are formatted in the invariant culture, whatever the server's (as ClassicBattlegrounds does).
    public static string DiedLine(string name, long id, eRealm realm, eAutonomousObjectiveKind goal, eRealm killerRealm,
        bool worth, long sinceLastDeathMilliseconds, ushort region, int x, int y, int z) =>
        string.Create(CultureInfo.InvariantCulture,
            $"{LogPrefix} action=died bot={name} id={id} realm={GlobalConstants.RealmToName(realm)} goal={goal} " +
            $"killerRealm={GlobalConstants.RealmToName(killerRealm)} worth={(worth ? "yes" : "no")} " +
            $"sinceLastDeath={(sinceLastDeathMilliseconds < 0 ? "none" : Seconds(sinceLastDeathMilliseconds))} " +
            $"region={region} position={x},{y},{z}");

    // 10.5: "HEARTHDAOC_RP_WAIT action=start bot=<name> id=<id> realm=<RealmToName> case=<CaseWord> region=<Region>
    // worthIn=<Seconds> trip=<Seconds> leaveIn=<Seconds> spot=<(int)X>,<(int)Y>,<(int)Z>" + " group=<SessionId>" when
    // the marker has a SessionId. The marker is the Waiting one just swapped in.
    public static string StartLine(string name, long id, eRealm realm, RpWaitMarker started, long timeLeft,
        long tripMilliseconds, long leaveInMilliseconds) =>
        string.Create(CultureInfo.InvariantCulture,
            $"{LogPrefix} action=start bot={name} id={id} realm={GlobalConstants.RealmToName(realm)} " +
            $"case={CaseWord(started.Case)} region={started.Region} worthIn={Seconds(timeLeft)} " +
            $"trip={Seconds(tripMilliseconds)} leaveIn={Seconds(leaveInMilliseconds)} " +
            $"spot={(int)started.Spot.X},{(int)started.Spot.Y},{(int)started.Spot.Z}{GroupField(started)}");

    // 10.5: "HEARTHDAOC_RP_WAIT action=skip bot=<name> id=<id> realm=<RealmToName> case=<CaseWord> worthIn=<Seconds>
    // reason=<ReasonWord>"
    public static string SkipLine(string name, long id, eRealm realm, RpWaitCase hookCase, long timeLeft,
        RpWaitReason reason) =>
        string.Create(CultureInfo.InvariantCulture,
            $"{LogPrefix} action=skip bot={name} id={id} realm={GlobalConstants.RealmToName(realm)} " +
            $"case={CaseWord(hookCase)} worthIn={Seconds(timeLeft)} reason={ReasonWord(reason)}");

    // 10.5: "HEARTHDAOC_RP_WAIT action=leave bot=<name> id=<id> realm=<RealmToName> case=<CaseWord> waited=<Seconds>
    // worthIn=<Seconds> trip=<Seconds> reason=<ReasonWord>" + " group=<SessionId>" when the marker has one. The marker is
    // the Waiting one before the leave; tripMilliseconds -1 (unknown) prints "-".
    public static string LeaveLine(string name, long id, eRealm realm, RpWaitMarker waiting, long waitedMilliseconds,
        long timeLeft, long tripMilliseconds, RpWaitReason reason) =>
        string.Create(CultureInfo.InvariantCulture,
            $"{LogPrefix} action=leave bot={name} id={id} realm={GlobalConstants.RealmToName(realm)} " +
            $"case={CaseWord(waiting.Case)} waited={Seconds(waitedMilliseconds)} worthIn={Seconds(timeLeft)} " +
            $"trip={Seconds(tripMilliseconds)} reason={ReasonWord(reason)}{GroupField(waiting)}");

    // The start and leave lines' last field: " group=<SessionId>" for a marker with a session id, else nothing.
    private static string GroupField(RpWaitMarker marker) =>
        string.IsNullOrEmpty(marker.SessionId) ? "" : " group=" + marker.SessionId;

    // The writers: Log.Info(line) when Log.IsInfoEnabled, with bot.Name, bot.DatabaseID and bot.Realm.
    public static void WriteStart(GameBot bot, RpWaitMarker started, long timeLeft, long tripMilliseconds,
        long leaveInMilliseconds)
    {
        if (Log.IsInfoEnabled)
            Log.Info(StartLine(bot.Name, bot.DatabaseID, bot.Realm, started, timeLeft, tripMilliseconds,
                leaveInMilliseconds));
    }

    public static void WriteSkip(GameBot bot, RpWaitCase hookCase, long timeLeft, RpWaitReason reason)
    {
        if (Log.IsInfoEnabled)
            Log.Info(SkipLine(bot.Name, bot.DatabaseID, bot.Realm, hookCase, timeLeft, reason));
    }

    // waited = now - waiting.Started.
    public static void WriteLeave(GameBot bot, RpWaitMarker waiting, long now, long timeLeft, long tripMilliseconds,
        RpWaitReason reason)
    {
        if (Log.IsInfoEnabled)
            Log.Info(LeaveLine(bot.Name, bot.DatabaseID, bot.Realm, waiting, now - waiting.Started, timeLeft,
                tripMilliseconds, reason));
    }
}

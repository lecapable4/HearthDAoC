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

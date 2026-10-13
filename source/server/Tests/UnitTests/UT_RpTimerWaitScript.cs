using System;
using System.Collections;
using System.Collections.Generic;
using System.Numerics;
using System.Reflection;
using System.Runtime.CompilerServices;
using DOL.Database;
using DOL.GS.HearthDAoC;
using DOL.GS.ServerProperties;
using DOL.GS.ServerRules;
using NUnit.Framework;

namespace DOL.GS.Tests;

// HearthDAoC: gamebots come back worth realm points (spec docs/fork/specs/2026-10-13-rp-timer-waits-design.md,
// 10.1 "Wiring"). RpTimerWaitScript is the game wiring of the waits: the bot_rp_timer_wait switch, the reads of a
// bot's realm point timer, speed, slot and death record, the HEARTHDAOC_RP_WAIT log lines, and the entry points the
// upstream hooks call. RpTimerWait makes every decision (UT_RpTimerWait); these tests check the wiring around it, on
// gamebots made without their constructor.
[TestFixture]
public sealed class UT_RpTimerWaitScript
{
    // GameObject's type initializer reads the database (FillDataQuestCache): a test double server with an empty
    // database, as UT_AutonomousBotRealmPointRewards does, before any GameBot is made.
    private sealed class EmptyServer : GameServer
    {
        protected override IServerRules ServerRulesImpl => new NormalServerRules();
        protected override IObjectDatabase DataBaseImpl => EmptyDatabase;
    }

    public class EmptyReads : DispatchProxy
    {
        protected override object Invoke(MethodInfo method, object[] args)
        {
            Type result = method.ReturnType;
            if (result.IsGenericType && typeof(IEnumerable).IsAssignableFrom(result))
                return Activator.CreateInstance(typeof(List<>).MakeGenericType(result.GetGenericArguments()[0]));
            return null;
        }
    }

    private static readonly IObjectDatabase EmptyDatabase = DispatchProxy.Create<IObjectDatabase, EmptyReads>();

    private GameServer _savedServer;
    private int _savedRpWorthSeconds;
    private long _savedTime;
    private bool _savedSwitch;

    [SetUp]
    public void SaveGlobals()
    {
        _savedServer = GameServer.Instance;
        GameServer.LoadTestDouble((EmptyServer)RuntimeHelpers.GetUninitializedObject(typeof(EmptyServer)));
        _savedRpWorthSeconds = Properties.RP_WORTH_SECONDS;
        _savedTime = GameLoop.GameLoopTime;
        _savedSwitch = RpTimerWaitScript.BOT_RP_TIMER_WAIT;
    }

    [TearDown]
    public void RestoreGlobals()
    {
        Properties.RP_WORTH_SECONDS = _savedRpWorthSeconds;
        SetTime(_savedTime);
        RpTimerWaitScript.BOT_RP_TIMER_WAIT = _savedSwitch;
        GameServer.LoadTestDouble(_savedServer);
    }

    private static void SetTime(long value) =>
        typeof(GameLoop).GetProperty(nameof(GameLoop.GameLoopTime)).SetValue(null, value);

    // A gamebot without its constructor: only its TempProperties are real.
    private static GameBot Bot()
    {
        GameBot bot = (GameBot)RuntimeHelpers.GetUninitializedObject(typeof(GameBot));
        typeof(GameLiving).GetField("<TempProperties>k__BackingField", BindingFlags.Instance | BindingFlags.NonPublic)!
            .SetValue(bot, new PropertyCollection());
        return bot;
    }

    [Test]
    public void TheSwitchIsAPublicStaticServerPropertyOffInCode()
    {
        // The server finds a property only on a public static field (ServerProperties.AllDomainProperties reads
        // GetFields(), then IsStatic). HearthDAoC turns it on through HEARTHDAOC_BOT_RP_TIMER_WAIT; the description
        // must equal deploy/bin/server_properties.py's RP_WAIT_DESCRIPTION (deploy/tests/test_rp_timer_wait.py).
        FieldInfo field = Array.Find(typeof(RpTimerWaitScript).GetFields(), f => f.Name == "BOT_RP_TIMER_WAIT");
        Assert.That(field, Is.Not.Null);
        Assert.That(field.IsStatic, Is.True);
        Assert.That(field.FieldType, Is.EqualTo(typeof(bool)));
        ServerPropertyAttribute property = field.GetCustomAttribute<ServerPropertyAttribute>();
        Assert.That(property, Is.Not.Null);
        Assert.That(property.Category, Is.EqualTo("server"));
        Assert.That(property.Key, Is.EqualTo("bot_rp_timer_wait"));
        Assert.That(property.DefaultValue, Is.TypeOf<bool>().And.EqualTo(false));
        Assert.That(property.Description, Is.EqualTo(
            "Released gamebots wait at a safe spot until their trip back to the fight ends as their rp_worth_seconds " +
            "timer does, so they come back worth realm points"));
    }

    // Albion's capital anchor (AutonomousStuckWatchdog.CapitalFor), where a battleground or warband bot releases.
    private static readonly Vector3 Camelot = new(35_990, 30_298, 8_000);

    [Test]
    public void RealmPointDeathTickIsMinusOneForABotNeverKilled()
    {
        // ARPR:83-84 reads a missing timer as -1: no death on record, so the bot is worth realm points.
        Properties.RP_WORTH_SECONDS = 300;
        SetTime(1_100_000);
        GameBot bot = Bot();
        Assert.That(RpTimerWaitScript.RealmPointDeathTick(bot), Is.EqualTo(-1));
        Assert.That(RpTimerWaitScript.WorthlessFor(bot), Is.EqualTo(0));
    }

    [Test]
    public void WorthlessForReadsTheRealmPointTimerKey()
    {
        // The upstream key spelled out: the test project can't see ARPR's internal const. Stored as ARPR:90 writes it,
        // GameLoopTime as a long (GetProperty<long> reads an int as no death at all).
        Properties.RP_WORTH_SECONDS = 300;
        GameBot bot = Bot();
        bot.TempProperties.SetProperty("autonomous.rvr.last.realm.point.death.tick", 1_000_000L);
        SetTime(1_100_000);
        Assert.That(RpTimerWaitScript.RealmPointDeathTick(bot), Is.EqualTo(1_000_000));
        Assert.That(RpTimerWaitScript.WorthlessFor(bot), Is.EqualTo(200_000));
        SetTime(1_300_000);
        Assert.That(RpTimerWaitScript.WorthlessFor(bot), Is.EqualTo(0));
    }

    [Test]
    public void WorthlessForIsZeroWhenRpWorthSecondsIsZero()
    {
        // rp_worth_seconds 0 turns the timer off (ARPR:85-86): every kill pays, so a bot just killed is worth points.
        Properties.RP_WORTH_SECONDS = 0;
        GameBot bot = Bot();
        bot.TempProperties.SetProperty("autonomous.rvr.last.realm.point.death.tick", 1_000_000L);
        SetTime(1_000_001);
        Assert.That(RpTimerWaitScript.WorthlessFor(bot), Is.EqualTo(0));
    }

    [Test]
    public void TheSlotAndTheDeathRecordAreReadFromTheirKeys()
    {
        GameBot bot = Bot();
        Assert.That(RpTimerWaitScript.SlotOf(bot), Is.Null);
        Assert.That(RpTimerWaitScript.DeathRecordOf(bot), Is.Null);

        var slot = new RpWaitSlot();
        var death = new RpDeathRecord(3, 252, new Vector3(36_412, 51_377, 3_950), 1_000_000, 700_000);
        bot.TempProperties.SetProperty("hearthdaoc.rp.wait", slot);
        bot.TempProperties.SetProperty("hearthdaoc.rp.death", death);
        Assert.That(RpTimerWaitScript.SlotOf(bot), Is.SameAs(slot));
        Assert.That(RpTimerWaitScript.DeathRecordOf(bot), Is.SameAs(death));
        Assert.That(RpTimerWaitScript.WaitKey, Is.EqualTo("hearthdaoc.rp.wait"));
        Assert.That(RpTimerWaitScript.DeathKey, Is.EqualTo("hearthdaoc.rp.death"));
    }

    // 10.5: whole seconds, rounded to the nearest; "-" for unknown (a negative value), "never" for no speed.
    [TestCase(42_832L, "43")]
    [TestCase(11_239L, "11")]
    [TestCase(0L, "0")]
    [TestCase(499L, "0")]
    [TestCase(500L, "1")]
    [TestCase(-1L, "-")]
    [TestCase(long.MaxValue, "never")]
    public void SecondsRoundToTheNearestSecond(long milliseconds, string expected) =>
        Assert.That(RpTimerWaitScript.Seconds(milliseconds), Is.EqualTo(expected));

    [Test]
    public void EveryCaseAndReasonHasItsLogWord()
    {
        var cases = new Dictionary<RpWaitCase, string>
        {
            [RpWaitCase.None] = "none",
            [RpWaitCase.Battleground] = "battleground",
            [RpWaitCase.Frontier] = "frontier",
            [RpWaitCase.Siege] = "siege",
            [RpWaitCase.Warband] = "warband",
        };
        var reasons = new Dictionary<RpWaitReason, string>
        {
            [RpWaitReason.None] = "",
            [RpWaitReason.Trip] = "trip",
            [RpWaitReason.OtherRegion] = "other-region",
            [RpWaitReason.MovedAway] = "moved-away",
            [RpWaitReason.Relic] = "relic",
            [RpWaitReason.NoTarget] = "no-target",
            [RpWaitReason.Due] = "due",
            [RpWaitReason.Off] = "off",
            [RpWaitReason.Changed] = "changed",
            [RpWaitReason.Called] = "called",
            [RpWaitReason.PlayerGroup] = "player-group",
            [RpWaitReason.Battle] = "battle",
            [RpWaitReason.Died] = "died",
        };
        Assert.That(cases.Keys, Is.EquivalentTo(Enum.GetValues<RpWaitCase>()));
        Assert.That(reasons.Keys, Is.EquivalentTo(Enum.GetValues<RpWaitReason>()));
        foreach ((RpWaitCase value, string word) in cases)
            Assert.That(RpTimerWaitScript.CaseWord(value), Is.EqualTo(word), value.ToString());
        foreach ((RpWaitReason value, string word) in reasons)
            Assert.That(RpTimerWaitScript.ReasonWord(value), Is.EqualTo(word), value.ToString());
    }

    [Test]
    public void TheDiedLine()
    {
        // Killed again 61 s after its last death: the kill paid nothing.
        Assert.That(RpTimerWaitScript.DiedLine("Aldwin", 42, eRealm.Albion, eAutonomousObjectiveKind.Battleground,
                eRealm.Midgard, false, 61_400, 252, 36_412, 51_377, 3_950),
            Is.EqualTo("HEARTHDAOC_RP_WAIT action=died bot=Aldwin id=42 realm=Albion goal=Battleground " +
                       "killerRealm=Midgard worth=no sinceLastDeath=61 region=252 position=36412,51377,3950"));
    }

    [Test]
    public void TheDiedLineOfAFirstDeath()
    {
        // No death record before this one: the kill paid, and there is no time since a last death.
        Assert.That(RpTimerWaitScript.DiedLine("Eadric", 108, eRealm.Albion, eAutonomousObjectiveKind.RvR,
                eRealm.Hibernia, true, -1, 1, 552_100, 498_300, 2_400),
            Is.EqualTo("HEARTHDAOC_RP_WAIT action=died bot=Eadric id=108 realm=Albion goal=RvR killerRealm=Hibernia " +
                       "worth=yes sinceLastDeath=none region=1 position=552100,498300,2400"));
    }

    [Test]
    public void TheStartLine()
    {
        // A battleground wait at its slot by its realm's arrival point (the region is the wait's, not the release's):
        // worth points in 270 s, 11.239 s from the first contact point, so it leaves in 258.761 s. The spot is the
        // navmesh-snapped slot as stored, cut to whole units.
        var started = new RpWaitMarker(3, RpWaitPhase.Waiting, RpWaitCase.Battleground, 10, Camelot, 252,
            new Vector3(36_500.7f, 51_400.2f, 3_952.9f), "albion-20-12-Battleground", null, null, 1_030_000);
        Assert.That(RpTimerWaitScript.StartLine("Aldwin", 42, eRealm.Albion, started, 270_000, 11_239, 258_761),
            Is.EqualTo("HEARTHDAOC_RP_WAIT action=start bot=Aldwin id=42 realm=Albion case=battleground region=252 " +
                       "worthIn=270 trip=11 leaveIn=259 spot=36500,51400,3952"));
    }

    [Test]
    public void TheStartLineOfAWarbandMemberNamesItsGroup()
    {
        // The gate's line for one member at its slot by the border keep: its own time left, the march as its trip,
        // and the holder's time left less the march as leaveIn.
        var started = new RpWaitMarker(3, RpWaitPhase.Waiting, RpWaitCase.Warband, 10, Camelot, 1,
            new Vector3(29_640, 31_220, 4_310), "albion-40-12-RvR", "albion-7f3a-007", null, 1_030_000);
        Assert.That(RpTimerWaitScript.StartLine("Beorn", 77, eRealm.Albion, started, 238_400, 50_000, 190_000),
            Is.EqualTo("HEARTHDAOC_RP_WAIT action=start bot=Beorn id=77 realm=Albion case=warband region=1 " +
                       "worthIn=238 trip=50 leaveIn=190 spot=29640,31220,4310 group=albion-7f3a-007"));
    }

    [Test]
    public void TheSkipLine()
    {
        Assert.That(RpTimerWaitScript.SkipLine("Sigrun", 1_077, eRealm.Midgard, RpWaitCase.Frontier, 120_400,
                RpWaitReason.OtherRegion),
            Is.EqualTo("HEARTHDAOC_RP_WAIT action=skip bot=Sigrun id=1077 realm=Midgard case=frontier worthIn=120 " +
                       "reason=other-region"));
    }

    [Test]
    public void TheLeaveLine()
    {
        // A drafted warband member's siege wait, its group kept, ends when its time left reaches its trip to the keep.
        var waiting = new RpWaitMarker(3, RpWaitPhase.Waiting, RpWaitCase.Siege, 10, Camelot, 1,
            new Vector3(29_640, 31_220, 4_310), "albion-40-12-RvR", "albion-7f3a-007", "rvr-keep-50", 1_030_000);
        Assert.That(RpTimerWaitScript.LeaveLine("Beorn", 77, eRealm.Albion, waiting, 228_600, 41_400, 42_832,
                RpWaitReason.Due),
            Is.EqualTo("HEARTHDAOC_RP_WAIT action=leave bot=Beorn id=77 realm=Albion case=siege waited=229 " +
                       "worthIn=41 trip=43 reason=due group=albion-7f3a-007"));
    }

    [Test]
    public void TheLeaveLineWithNoTripKnown()
    {
        // Hook 3's leaves and the handlers' know no trip (-1): here the switch was turned off during a frontier wait.
        var bind = new Vector3(552_100, 498_300, 2_400);
        var waiting = new RpWaitMarker(3, RpWaitPhase.Waiting, RpWaitCase.Frontier, 1, bind, 1, bind,
            "albion-40-12-RvR", null, null, 1_030_000);
        Assert.That(RpTimerWaitScript.LeaveLine("Eadric", 108, eRealm.Albion, waiting, 95_000, 175_000, -1,
                RpWaitReason.Off),
            Is.EqualTo("HEARTHDAOC_RP_WAIT action=leave bot=Eadric id=108 realm=Albion case=frontier waited=95 " +
                       "worthIn=175 trip=- reason=off"));
    }
}

using System;
using System.Collections;
using System.Collections.Generic;
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
}

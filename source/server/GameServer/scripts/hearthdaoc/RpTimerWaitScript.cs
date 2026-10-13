using System;
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
}

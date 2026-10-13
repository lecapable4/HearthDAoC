# Gamebots come back worth realm points (stage 1): implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A gamebot killed in RvR or a battleground and released waits at a safe spot (its realm's battleground
arrival point, its bind, or its warband's slot at the border keep) and leaves when its time left is no more than its
trip back, so it arrives just as it is worth realm points again; a frontier warband leaves together; a bot resurrected
where it fell fights on. The realm point timer itself is unchanged. One switch, `bot_rp_timer_wait`, off in code and on
in HearthDAoC.

**Architecture:** A fork file (`scripts/hearthdaoc/RpTimerWait.cs`) makes every decision on plain values: a per-bot
immutable marker (Released, Waiting, Left) held in an `RpWaitSlot` and changed only by compare-and-set; time left, best
speed, trip, first contact point, leave tick and think wake; `Note` (a release), `Decide` (the first look and the wait),
the warband gate (`WarbandWaits`, `WarbandMarks`), `Died`, `JoinedGroup` and `IsWaiting`. `RpTimerWaitScript.cs` is the
game wiring: the `[ServerProperty]` switch, the timer and speed reads, the entry points hooks 3-6 call, the `Dying` and
`MemberJoined` handlers, and the `HEARTHDAOC_RP_WAIT` log. `RpTimerWaitController.cs` is a fork part of
`AutonomousWorldBotController` holding the battleground and RvR waits. Six one-line hooks, each under a `// HearthDAoC:`
comment, in four upstream files call them; `HEARTHDAOC_BOT_RP_TIMER_WAIT` turns the switch on through
`deploy/bin/server_properties.py` at every start.

**Tech Stack:** C# (.NET 10, NUnit 4) for the server and its unit tests; Python 3 `unittest` source and deploy checks in
`deploy/tests`; GitHub Actions CI (`.github/workflows/server-image.yml`).

**Spec:** `docs/fork/specs/2026-10-13-rp-timer-waits-design.md` (approved by the owner 2026-10-13 as stage 1; read it
with this plan). Battleground waves are deferred (the spec's Appendix B) and are not in this plan: every battleground bot
leaves at its own moment. Every code block below was built and tested in a scratch copy of this branch before the plan
was written, task by task as the steps say, and every `Expected:` is the output seen there (184 new unit tests:
`UT_RpTimerWait` 160, `UT_RpTimerWaitScript` 24; CI's whole unit filter 608, `UT_` 3,333, `deploy/tests` 627 OK), then
dry-run step by step in a fresh copy, where every `Expected:` matched (only build warning totals vary).

## Global Constraints

- Work in `~/github/HearthDAoC-rp`, branch `rp-timer-waits` (main merged in at 5a44c2d, v0.35b-hearth.19, plus the
  approved spec at 56fbe98). Never commit to `main`; never push to or open anything on `shadowofze/OfflineDAoC` or
  OpenDAoC: nothing goes upstream (paused by the owner). Implementers don't push or open PRs; the controller does at the
  end. Implementers never dispatch subagents. Nobody contacts the owner's server; the in-game checks are the owner's.
- Every commit message is `type(scope): a plain lower-case sentence`, a wrapped prose body, and ends with the line
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. The scope is `rp-wait`.
- **Line endings and BOMs stay exactly as they are** (measured at 56fbe98): `AutonomousWorldBotController.Battleground.cs`
  is CRLF; `AutonomousWorldBotController.cs`, `AutonomousWorldBotController.FrontierThreat.cs`,
  `AutonomousBotGroupCoordinator.cs` and every fork, deploy, CI and docs file this plan touches are LF. None has a BOM;
  all indent with spaces, no tabs. Edit existing files **only** with the helper below, which keeps both; `git diff --stat`
  must show only your lines.
- New fork files (`scripts/hearthdaoc/RpTimerWait*.cs`, `Tests/UnitTests/UT_RpTimerWait*.cs`,
  `deploy/tests/test_rp_timer_wait.py`, the verification guide) are LF, no BOM, spaces, with a file-scoped namespace,
  like `scripts/hearthdaoc/SiStartChoice.cs` and `SiStartChoiceScript.cs`, even though `source/server/.editorconfig` says
  CRLF and block-scoped. Create them with the Write tool or a quoted heredoc exactly as given.
- Create the edit helper once, at `/tmp/hdc-edit.py` (outside the repository), before Task 1:

```python
#!/usr/bin/env python3
"""Replaces text in one file, keeping its BOM and its line endings (CRLF or LF).

Usage: python3 /tmp/hdc-edit.py FILE <<'EDIT' ... EDIT
The input holds one or more blocks, each:
<<<<<<< OLD
the old text (LF line ends; converted to CRLF when the file is CRLF)
=======
the new text
>>>>>>> NEW
Each old text must occur exactly once in the file; otherwise nothing is written and the run stops.
"""
import sys

path = sys.argv[1]
with open(path, "rb") as f:
    raw = f.read()
crlf = b"\r\n" in raw
blocks = []
for part in sys.stdin.read().split("<<<<<<< OLD\n")[1:]:
    old, rest = part.split("=======\n", 1)
    new = rest.split(">>>>>>> NEW\n", 1)[0]
    blocks.append((old, new))
if not blocks:
    sys.exit("no edit blocks")
for old, new in blocks:
    o, n = old.encode("utf-8"), new.encode("utf-8")
    if crlf:
        o, n = o.replace(b"\n", b"\r\n"), n.replace(b"\n", b"\r\n")
    count = raw.count(o)
    if count != 1:
        sys.exit(f"{path}: old text found {count} times: {old[:80]!r}")
    raw = raw.replace(o, n)
with open(path, "wb") as f:
    f.write(raw)
print(f"edited {path} ({len(blocks)} block(s))")
```

- Run every command, edit block and `git add` from the repository root, `~/github/HearthDAoC-rp`, after checking that
  `git branch --show-current` prints `rp-timer-waits` (if it prints another name, `git switch rp-timer-waits`; if it
  prints nothing, you are in a detached checkout: stop and ask the controller).
- Test commands (each run in a scratch copy of this branch while writing the plan):
  - Unit tests need `source/server/CoreServer/config/serverconfig.xml` (gitignored; never commit it). If it is missing:
    `cp deploy/serverconfig.build.xml source/server/CoreServer/config/serverconfig.xml`.
  - Build only: `dotnet build source/server/Tests/Tests.csproj --nologo -v q -clp:ErrorsOnly`
    (Expected: `Build succeeded.` and `0 Error(s)`).
  - The decisions' class only: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWait."`
    (the trailing dot matters: `FullyQualifiedName~UT_RpTimerWait` also matches `UT_RpTimerWaitScript`).
  - The wiring's class: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWaitScript."`.
  - One deploy test file: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_rp_timer_wait.py` (the same
    with `-p test_server_properties.py`, `-p test_si_start_choice.py`, `-p test_workflows.py`, `-p test_battlegrounds.py`).
  - CI's unit filter (Tasks 9-12), with the CI step's own environment: the step "Server unit tests for the fork's server
    changes" sets `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT: "0"` in its `env:`, not on its `dotnet test` line, and the
    owner's `~/.bashrc` exports `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1`, under which 9 existing `UT_ClassicBattlegrounds`
    tests fail. So run it with the prefix, with the filter string of `server-image.yml` as it stands after Task 7:
    `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_CommandPrivLevelOverrides|FullyQualifiedName~UT_SiStartChoice|FullyQualifiedName~UT_ClassicBattlegrounds|FullyQualifiedName~UT_DataQuestDependency|FullyQualifiedName~UT_DataQuestDeliveryItem|FullyQualifiedName~UT_DataQuestOffers|FullyQualifiedName~UT_QuestJournal|FullyQualifiedName~UT_DataQuestWhisper|FullyQualifiedName~UT_QuestNames|FullyQualifiedName~UT_ClassicQuestsExtra|FullyQualifiedName~UT_ClassicQuestsChoice|FullyQualifiedName~UT_LinkedCamps|FullyQualifiedName~UT_EpicChain|FullyQualifiedName~UT_QuestIndicatorProbe|FullyQualifiedName~UT_QuestIndicators|FullyQualifiedName~UT_IndicatorSentStore|FullyQualifiedName~UT_RpTimerWait|FullyQualifiedName~UT_RpTimerWaitScript"`
    (424 tests at 56fbe98, 608 once Task 9 is in, with `UT_RpTimerWait` and `UT_RpTimerWaitScript`; Expected:
    `Passed!`, `Failed: 0`).
  - Everything: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_"`
    (3,149 at 56fbe98, 3,333 after this plan) and, from `deploy/`, `HDC_TEST_WORLD=/home/farral/Games/OfflineDAoC-archive/test-world/clean-classic-0.35.db HDC_CLASSIC_QUESTS=/home/farral/Games/DAoC/research/gos-epic-2026-10-09/classic-quests.json python3 -m unittest discover -s tests -t .`
    (600 tests, `OK (skipped=11)` at 56fbe98; 627 after this plan).
  - Upstream's `PooledWalReadersAndWriters_CanOpenConnectionsConcurrently` can fail with "database is locked" when the
    machine is busy (e.g. both suites at once). Run the suites one after the other; if it fails, rerun it alone and say so.
- `UT_RpTimerWaitScript` builds `GameBot`s without their constructor (`RuntimeHelpers.GetUninitializedObject`). `GameObject`'s
  type initializer reads the database (`FillDataQuestCache`), so its `[SetUp]` first loads a test double server with an
  empty database, as `UT_AutonomousBotRealmPointRewards` does (Task 7 gives the code); without it the first `GameBot`
  throws `TypeInitializationException` and poisons every later test in the run.
- The spec's values (owner-approved; do not change them):
  - Property `bot_rp_timer_wait`, category `server`, declared in `RpTimerWaitScript` as `public static bool
    BOT_RP_TIMER_WAIT`, code default `false`, description "Released gamebots wait at a safe spot until their trip back to
    the fight ends as their rp_worth_seconds timer does, so they come back worth realm points".
  - `HEARTHDAOC_BOT_RP_TIMER_WAIT`: `on` or `off`, case ignored, default `on` at every step (`.env`, `compose.yml`,
    `entrypoint.sh`); a bad value stops the start with exit 2 and "ERROR: HEARTHDAOC_BOT_RP_TIMER_WAIT must be on or off,
    got '…'". `server_properties.py` prints "Bot realm point timer wait: on" (or "off") when it changes the row.
  - TempProperty keys: `hearthdaoc.rp.wait` (the bot's `RpWaitSlot`) and `hearthdaoc.rp.death` (its `RpDeathRecord`).
    The timer is upstream's `autonomous.rvr.last.realm.point.death.tick` (read through ARPR's internal const in the fork,
    as the literal string in tests).
  - Constants (`RpTimerWait`): first-look gates 750 (bind, `BindGate`), 2,500 (battleground arrival, `ArrivalGate`) and
    200 (a drafted warband member's slot, `SlotGate`); walk back beyond 200 (`WalkBackBeyond`; a wait's later turns);
    a first look walks to its spot beyond 48 (`SpotTolerance`, IssuePath's arrival radius: a ruling, not a spec value,
    so a battleground bot landed on slot 0 still walks to its slot 160-330 away); first contact point 0.6
    (`ContactShare`), 900 (`PatrolRadius`) and 5,000 (`ScanRadius`); frontier regions 1, 100 and 200; battleground regions
    250-253; think wake at least 250 ms (`WakeFloorMilliseconds`) and the leave moment plus half a game tick rounded up
    (17 ms at 30 ticks/s).
  - The warband gate turns a Released member Waiting only while its time left is above 0 (a ruling, not in the spec's
    3.4 or 10.1, as the first look skips a bot already worth points with no line): such a member stays Released while
    the gate holds, with no `start` line, and the gate's opening latches it with no line (Task 5's `WarbandMark` and
    `WhileHoldingAReleasedMemberAlreadyWorthStaysReleased`; Task 9's `turnsWaiting` reads the same `timeLeft > 0`).
  - All distances (gates, walk-back, trips, the warband march) are horizontal (X, Y): `RpTimerWait.Distance2D`.
  - The log: one `Log.Info` line per event, prefix `HEARTHDAOC_RP_WAIT`, exactly (seconds are whole, rounded to the
    nearest; `-` for unknown; `never` for no speed):
    - `HEARTHDAOC_RP_WAIT action=died bot=<name> id=<id> realm=<Realm> goal=<goal> killerRealm=<Realm> worth=<yes|no> sinceLastDeath=<s|none> region=<region> position=<x>,<y>,<z>`
    - `HEARTHDAOC_RP_WAIT action=start bot=<name> id=<id> realm=<Realm> case=<case> region=<region> worthIn=<s> trip=<s> leaveIn=<s> spot=<x>,<y>,<z>[ group=<session id>]`
    - `HEARTHDAOC_RP_WAIT action=skip bot=<name> id=<id> realm=<Realm> case=<case> worthIn=<s> reason=<reason>`
    - `HEARTHDAOC_RP_WAIT action=leave bot=<name> id=<id> realm=<Realm> case=<case> waited=<s> worthIn=<s> trip=<s|-> reason=<reason>[ group=<session id>]`
    - `<Realm>` is `GlobalConstants.RealmToName`; `<goal>` the `eAutonomousObjectiveKind` name; `<case>` one of
      `battleground`, `frontier`, `siege`, `warband` (`none` for an unclassified marker); `<reason>` one of `trip`,
      `other-region`, `moved-away`, `relic`, `no-target`, `due`, `off`, `changed`, `called`, `player-group`, `battle`,
      `died`.
    - A `start`, `skip` or `leave` line is written only after its marker swap succeeds; `died` with the switch on or off.
- Out of scope (state it, don't build it): battleground waves (spec Appendix B); a seventh upstream hook (rebuffing pet
  classes, a siege-party filter); any change to the timer or `rp_worth_seconds`; the longer corpse wait.

## Review Focus

The inputs and conditions most likely to bite the owner in game that unit tests can't reach (they need a live server,
its threads, the navmesh and players), and the check that pins each:

1. **A hook in the wrong place after an upstream sync.** Hook 3 between WBC:323 and :324 would split a braceless `if`;
   hook 1 before the region check would hold bots in their capital; hook 2 after the target search or the relic
   branches would let a waiting bot be re-tasked; hook 6 after `.OrderBy(` would filter nothing. Pinned by the source
   checks `UpstreamHookTests` (Task 10) and `ControllerHookTests` (Task 11), each shown failing against the tree without
   the hooks, and the counts check (BG 1, WBC 2, GC 2, FT 1).
2. **Leaving on time when the woken think is taken.** A standing bot thinks every 2.5-11.7 s; the wait wakes one think at
   its leave moment, and a rebuff, pet upkeep, a cast or a fight can take that turn. The bot must leave late, never
   early, and never sit past its moment by more than its next hook turn. Pinned by `UT_RpTimerWait`'s
   `TheWakeIsTheLeaveMomentPlusHalfATickRoundedUp`, `TheWakeIsAtLeast250Milliseconds`,
   `TheStandardIntervalWinsWhenItIsSooner` (Task 2) and `AWaitHoldsUntilTimeLeftEqualsTheTrip` (Task 4), and in game:
   outside fights, each `leave reason=due` comes within about 12 s after its `start`'s `leaveIn`; a bot fighting at its
   moment leaves on its first turn after the fight, 10 s after the last blow (verification guide, checks 2 and 4).
3. **Markers written from several threads at once.** The warband gate writes other members' markers under the
   coordinator lock while their own hooks, the `Dying` handler and the `MemberJoined` handler write on other threads: a
   lost update would leave a wait running, a double write would log two `leave` lines. Pinned by the slot tests (Task 1),
   `KilledWhileReleasedLatchesWithNoLineAndAStaleSwapFails` (Task 3) and `AMarkerThatTurnsLeftBetweenReadAndWriteStaysLeft`
   (Task 5), and in game: every `start` has exactly one `leave` (the guide's count check).
4. **A waiting bot at a battleground arrival point that sees or is hit by enemies.** The threat scan runs before hook 1 on
   the first think inside, and arrival points are not safe areas: the bot must not charge an enemy it only sees, must
   fight back when it or a realm-mate within 1,000 is attacked, and must walk back to its spot after the fight; landed
   together on the arrival point, bots must walk apart to their own slots. Pinned by
   `AReleasedBotNearItsBattlegroundArrivalCounts` (Task 6), `AWaitFarFromItsSpotHoldsAndWalksBack` and
   `TheFirstLookWalksToABattlegroundSlotOnly160Away` (Task 4),
   `UpstreamHookTests.test_the_threat_scan_filter_is_inside_the_nearby_chain` (Task 10), and in game check 3.
5. **A waiting bot killed and resurrected, or invited by a player.** No hook sees a player-led bot and a resurrection
   sets no release, so only the event handlers end those waits; a stale wait would hold a resurrected bot or walk an
   invited one back to its spot after the player drops it. Pinned by `KilledWhileWaitingEndsTheWait`,
   `AfterADeathAResurrectionIsIgnoredAndAReleaseIsNotedAgain`, `JoiningAPlayersGroupEndsAWaitOrARelease` (Task 3),
   `ScriptWiringTests.test_the_script_registers_the_death_and_group_handlers` (Task 9), and in game checks 5 and 6.

## Files

| File | Task | Responsibility |
|---|---|---|
| `source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs` (new) | 1-6 | The decisions on plain values: the marker types and `RpWaitSlot` (1); time left, best speed, trip, first contact point, leave tick, think wake, constants (2); `Note`, `Died`, `JoinedGroup` (3); `WaitSpot`, `Decide` (4); `WarbandWaits`, `WarbandMarks` (5); `IsWaiting` (6) |
| `source/server/Tests/UnitTests/UT_RpTimerWait.cs` (new) | 1-6 | Every rule of the decisions (spec 10.1) |
| `source/server/GameServer/scripts/hearthdaoc/RpTimerWaitScript.cs` (new) | 7, 8, 9 | The switch (7); the timer and speed reads and the log lines (8); `NoteRelease`, `IsWaiting(GameBot)`, `WarbandWaits(...)`, the `Dying` and `MemberJoined` handlers (9) |
| `source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs` (new) | 7, 8, 9 | The switch's declaration, `WorthlessFor` on the literal key, the log lines, the entry points' early returns |
| `source/server/GameServer/scripts/hearthdaoc/RpTimerWaitController.cs` (new) | 11 | A fork part of `AutonomousWorldBotController`: the battleground and RvR waits (hooks 1-2) |
| `source/server/GameServer/bots/autonomous/AutonomousWorldBotController.cs` | 10, 11 | Hook 3 in `Tick` (10); hook 2 in `ExecuteRvr` (11) |
| `source/server/GameServer/bots/autonomous/AutonomousBotGroupCoordinator.cs` | 10 | Hook 4 (the regroup completion) and hook 5 (`TryFormGroups`' recruiting filter) |
| `source/server/GameServer/bots/autonomous/AutonomousWorldBotController.FrontierThreat.cs` | 10 | Hook 6 (the threat scan's `nearby` chain) |
| `source/server/GameServer/bots/autonomous/AutonomousWorldBotController.Battleground.cs` (CRLF) | 11 | Hook 1 in `ExecuteBattleground` |
| `deploy/bin/server_properties.py`, `deploy/entrypoint.sh`, `deploy/compose.yml`, `deploy/.env.example`, `deploy/HANDOFF.md` | 7 | `HEARTHDAOC_BOT_RP_TIMER_WAIT` to `bot_rp_timer_wait`, default on, documented |
| `deploy/tests/test_server_properties.py`, `deploy/tests/test_si_start_choice.py` | 7 | Their CLI calls and expected output follow the new required argument |
| `deploy/tests/test_rp_timer_wait.py` (new) | 7, 8, 9, 10, 11 | The switch's deploy checks (7); source checks of the wiring (8, 9), of hooks 3-6 and the upstream facts (10), of hooks 1-2, the private members, the counts and the endings (11) |
| `.github/workflows/server-image.yml`, `deploy/tests/test_workflows.py` | 1, 7 | CI runs `UT_RpTimerWait` (1) and `UT_RpTimerWaitScript` (7) |
| `docs/fork/FORK.md`, `docs/fork/verification/rp-timer-waits-ingame.md` (new) | 12 | The record and the owner's in-game checks (spec 10.4, 10.5, 11) |

---

### Task 1: The wait marker and its compare-and-set slot

**Files:**
- Create: `source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs` (the types; the class `RpTimerWait` comes in
  Task 2)
- Create: `source/server/Tests/UnitTests/UT_RpTimerWait.cs`
- Modify: `.github/workflows/server-image.yml` (CI runs the new class)
- Modify: `deploy/tests/test_workflows.py` (the pinned filter and its list of names)
- Test: `source/server/Tests/UnitTests/UT_RpTimerWait.cs`, `deploy/tests/test_workflows.py`

**Spec:** 2.4 (the marker, never changed in place), 7.1 (the types), 7.2 (compare-and-set, the handlers' retry), 10.1
("Marker swap").

**Interfaces:**
- Consumes: nothing new (`System.Numerics.Vector3`; `System.Threading.Interlocked`, `Volatile`).
- Produces, in `namespace DOL.GS.HearthDAoC`:
  - `public enum RpWaitPhase { Released, Waiting, Left }`
  - `public enum RpWaitCase { None, Battleground, Frontier, Siege, Warband }`
  - `public enum RpWaitAction { None, Start, Skip, Leave, Convert }`
  - `public enum RpWaitReason { None, Trip, OtherRegion, MovedAway, Relic, NoTarget, Due, Off, Changed, Called,
    PlayerGroup, Battle, Died }`
  - `public enum RpWaitVerdict { Ignore, Skip, Start, Convert, Hold, Leave }`
  - `public sealed record RpWaitMarker(int DeathCount, RpWaitPhase Phase, RpWaitCase Case, ushort ReleaseRegion,
    Vector3 ReleasePoint, ushort Region, Vector3 Spot, string AssignmentId, string SessionId, string EventKeepId,
    long Started)`
  - `public sealed class RpWaitSlot` with `public RpWaitMarker Current { get; }` (null until the first marker),
    `public bool TrySwap(RpWaitMarker expected, RpWaitMarker next)` and
    `public RpWaitChange Apply(Func<RpWaitMarker, RpWaitChange> decide)`
  - `public sealed record RpDeathRecord(int DeathCount, ushort Region, Vector3 Position, long Tick, long TimerValue)`
  - `public readonly record struct RpWaitChange(RpWaitMarker Before, RpWaitMarker Next, RpWaitAction Action,
    RpWaitReason Reason)` with `public static RpWaitChange Keep(RpWaitMarker marker)` and `public bool Changes { get; }`
  - `public readonly record struct RpWaitLook(RpWaitCase Case, ushort Region, Vector3 Position, string AssignmentId,
    string EventKeepId, bool Relic, bool HasTarget, ushort TargetRegion, Vector3 Arrival, Vector3 BattlegroundSlot)`
  - `public readonly record struct RpWaitDecision(RpWaitVerdict Verdict, RpWaitReason Reason, RpWaitMarker Before,
    RpWaitMarker Next, RpWaitAction Action, bool WalkBack)`
  - `public readonly record struct RpWarbandMember(RpWaitMarker Marker, int DeathCount, long TimeLeft,
    RpDeathRecord Death, ushort Region, Vector3 Slot, string AssignmentId, double BestSpeed)`
  - `public readonly record struct RpWarbandGate(bool Waits, bool Writes, long MarchMilliseconds, long HolderTimeLeft)`

- [ ] **Step 1: Write the failing tests.** Create `source/server/Tests/UnitTests/UT_RpTimerWait.cs` with exactly:

```csharp
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
```

Then pin the new class in the workflow check: its copy of CI's filter string, and its list of names (each must be a
file holding `public sealed class UT_X`). CI's own filter follows in Step 3.

```bash
python3 /tmp/hdc-edit.py deploy/tests/test_workflows.py <<'EDIT'
<<<<<<< OLD
                     '|FullyQualifiedName~UT_QuestIndicators|FullyQualifiedName~UT_IndicatorSentStore"')
=======
                     '|FullyQualifiedName~UT_QuestIndicators|FullyQualifiedName~UT_IndicatorSentStore'
                     '|FullyQualifiedName~UT_RpTimerWait"')
>>>>>>> NEW
<<<<<<< OLD
                                 "UT_QuestIndicators", "UT_IndicatorSentStore"])
=======
                                 "UT_QuestIndicators", "UT_IndicatorSentStore",
                                 "UT_RpTimerWait"])
>>>>>>> NEW
EDIT
```

Expected: `edited deploy/tests/test_workflows.py (2 block(s))`.

- [ ] **Step 2: Run them and watch them fail.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWait."`
Expected: the build fails (exit code 1) and no test runs. The errors, each with the file's absolute path and the
project at the end of the line:

```
source/server/Tests/UnitTests/UT_RpTimerWait.cs(20,20): error CS0246: The type or namespace name 'RpWaitMarker' could not be found (are you missing a using directive or an assembly reference?)
source/server/Tests/UnitTests/UT_RpTimerWait.cs(24,40): error CS0246: The type or namespace name 'RpWaitMarker' could not be found (are you missing a using directive or an assembly reference?)
source/server/Tests/UnitTests/UT_RpTimerWait.cs(24,20): error CS0246: The type or namespace name 'RpWaitSlot' could not be found (are you missing a using directive or an assembly reference?)
```

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_workflows.py`
Expected: `FAIL: test_the_fork_server_unit_tests_run_with_the_pinned_filter` (CI's step does not name `UT_RpTimerWait`
yet), then `Ran 17 tests` and `FAILED (failures=1)`.

- [ ] **Step 3: Implement.** Create `source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs` with exactly the
code below: every type of the stage, each as its Interfaces list declares it, and the slot's two members. `TrySwap` is one
`Interlocked.CompareExchange`, which compares references, so a marker equal in every value never passes for the one
read. `Apply` reads, decides, and returns once the decision's marker is the one it read (nothing to write) or its swap
against the marker it read succeeds; a lost swap reads and decides again. The class `RpTimerWait` comes in Task 2,
after the file's last line.

```csharp
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
```

CI runs the new class:

```bash
python3 /tmp/hdc-edit.py .github/workflows/server-image.yml <<'EDIT'
<<<<<<< OLD
|FullyQualifiedName~UT_IndicatorSentStore"
=======
|FullyQualifiedName~UT_IndicatorSentStore|FullyQualifiedName~UT_RpTimerWait"
>>>>>>> NEW
EDIT
```

Expected: `edited .github/workflows/server-image.yml (1 block(s))`.

- [ ] **Step 4: Run them and watch them pass.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWait."`
Expected: `Passed!  - Failed:     0, Passed:     5, Skipped:     0, Total:     5` (exit code 0; no warning names
`RpTimerWait.cs` or `UT_RpTimerWait.cs`).

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_workflows.py`
Expected: `Ran 17 tests` and `OK`.

Run: `git diff --stat`
Expected: only ` .github/workflows/server-image.yml | 2 +-` and ` deploy/tests/test_workflows.py     | 6 ++++--`
(`2 files changed, 5 insertions(+), 3 deletions(-)`; the two new files are not tracked yet).

- [ ] **Step 5: Commit.**

```bash
git add source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs source/server/Tests/UnitTests/UT_RpTimerWait.cs .github/workflows/server-image.yml deploy/tests/test_workflows.py
git commit -F - <<'EOF'
feat(rp-wait): the wait marker and its compare-and-set slot

A bot's wait for one death is an immutable marker (Released, Waiting, Left) held in one slot per bot. Bot brains
tick in parallel and the warband gate writes other members' markers, so every write swaps a new marker in by
compare-and-set; the death and group handlers, which have no next turn, retry until their decision writes nothing
more. CI runs the new test class.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

Expected: `4 files changed, 368 insertions(+), 3 deletions(-)`.

---

### Task 2: Time left, best speed, trip, first contact point and the think wake

**Files:**
- Modify: `source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs` (add the class `RpTimerWait` after Task 1's
  types, with its constants and its arithmetic)
- Modify: `source/server/Tests/UnitTests/UT_RpTimerWait.cs` (25 tests at the class's end)
- Test: `source/server/Tests/UnitTests/UT_RpTimerWait.cs`

**Spec:** 2.1 (time left), 2.2 (trip, best speed), 2.3 (wait or go, the think wake), 3.1 (the first contact point),
7.1, 10.1 ("Time left", "Best speed", "Trip", "First contact", "Leave tick").

**Interfaces:**
- Consumes: Task 1's file (the class goes after its last line, `RpWarbandGate`'s); `System.Math`,
  `System.Numerics.Vector2`/`Vector3`; in the tests only, upstream's `BattlegroundBrackets.IsBattlegroundRegion(ushort)`
  (`DOL.GS`, `world/BattlegroundBrackets.cs:29`).
- Produces, in `namespace DOL.GS.HearthDAoC`, `public static class RpTimerWait` with:
  - `public const int BindGate = 750`, `ArrivalGate = 2_500`, `SlotGate = 200`, `WalkBackBeyond = 200`,
    `SpotTolerance = 48`, `PatrolRadius = 900`, `ScanRadius = 5_000`, `WakeFloorMilliseconds = 250`;
    `public const float ContactShare = 0.6f`; `public const ushort FirstBattlegroundRegion = 250`,
    `LastBattlegroundRegion = 253`, `AlbionFrontier = 1`, `MidgardFrontier = 100`, `HiberniaFrontier = 200`
  - `public static bool IsBattlegroundRegion(ushort region)`
  - `public static bool IsFrontierRegion(ushort region)`
  - `public static double Distance2D(Vector3 a, Vector3 b)`
  - `public static long WorthlessForMilliseconds(long lastDeathTick, long now, int rpWorthSeconds)`
  - `public static double BestSpeed(short maxSpeed, short maxSpeedBase, double bestOwnSpeedValue)`
  - `public static long TripMilliseconds(double distance, double unitsPerSecond)`
  - `public static Vector2 FirstContactPoint(Vector2 arrival, Vector2 centralKeep)`
  - `public static long LeaveTick(long lastDeathTick, int rpWorthSeconds, long tripMilliseconds)`
  - `public static int ThinkWakeMilliseconds(long leaveTick, long now, double tickDurationMilliseconds,
    int standardInterval)`

- [ ] **Step 1: Write the failing tests.** Add them at the end of the class in `UT_RpTimerWait.cs`, after Task 1's
last test, with the four values they share (a death at game time 1,000,000 with `rp_worth_seconds` 300; the central
keep; a game tick at 30 ticks a second):

```bash
python3 /tmp/hdc-edit.py source/server/Tests/UnitTests/UT_RpTimerWait.cs <<'EDIT'
<<<<<<< OLD
        Assert.That(new RpWaitChange(waiting, copy, RpWaitAction.None, RpWaitReason.None).Changes, Is.True);
    }
}
=======
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
}
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/Tests/UnitTests/UT_RpTimerWait.cs (1 block(s))`.

- [ ] **Step 2: Run them and watch them fail.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWait."`
Expected: the build fails (exit code 1) and no test runs. 45 errors, every one in the new tests and every one the same
(`RpTimerWait` does not exist yet, so CS0117 never comes up), each with the file's absolute path and the project at the
end of the line, from the first:

```
source/server/Tests/UnitTests/UT_RpTimerWait.cs(164,21): error CS0103: The name 'RpTimerWait' does not exist in the current context
```

to the last:

```
source/server/Tests/UnitTests/UT_RpTimerWait.cs(320,21): error CS0103: The name 'RpTimerWait' does not exist in the current context
```

- [ ] **Step 3: Implement.** Add the class after `RpWarbandGate`'s line, the file's last, with exactly the code below:
the constants and members, each under its rule comment. Time left is ARPR:82-86's own arithmetic
(`Math.Max(0, rp_worth_seconds) * 1000L`, then the rest of the interval, clamped), so it is 0 exactly when the reward
check pays. `Distance2D` and the trip work in `double`; the trip is floored, and a speed of 0 or below (or one so small
that the quotient would not fit a `long`) gives `long.MaxValue`, which no time left exceeds. `FirstContactPoint` works
on `Vector2` (float; the tests allow ±1, as 10.1 does) and returns the arrival itself when 0.6 x |AC| does not pass
900 + 5,000, which also covers A = C (no division by a zero length). `LeaveTick` clamps the trip to the interval first,
so `long.MaxValue` cannot overflow; `ThinkWakeMilliseconds` adds `ceil(tickDuration / 2)` in `long` and only then
compares with the standard interval and narrows to `int`.

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs <<'EDIT'
<<<<<<< OLD
public readonly record struct RpWarbandGate(bool Waits, bool Writes, long MarchMilliseconds, long HolderTimeLeft);
=======
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
}
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs (1 block(s))`.

- [ ] **Step 4: Run them and watch them pass.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWait."`
Expected: `Passed!  - Failed:     0, Passed:    30, Skipped:     0, Total:    30` (exit code 0; no warning names
`RpTimerWait.cs` or `UT_RpTimerWait.cs`). 30 = Task 1's 5 + this task's 25: 14 `[Test]` methods and 11 `[TestCase]`
rows (`ZeroOrNegativeRpWorthSecondsIsWorthAtOnce` 2, `TimeLeftAfterTheDeath` 4, `FirstContactIsOnTheLineToTheCentralKeep`
3, `TheWakeIsAtLeast250Milliseconds` 2).

Run: `git diff --stat`
Expected: only the two files, `RpTimerWait.cs` with 92 lines added and `UT_RpTimerWait.cs` with 171, then
`2 files changed, 263 insertions(+)`.

- [ ] **Step 5: Commit.**

```bash
git add source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs source/server/Tests/UnitTests/UT_RpTimerWait.cs
git commit -F - <<'EOF'
feat(rp-wait): time left, best speed, trip, first contact point and the think wake

Time left mirrors the reward check exactly (0 means worth). Best speed is the largest of the live speed, the base
speed and the base speed with the bot's own best speed song, because a released bot starts hurt and a singer starts
its song only once it moves. The trip is a straight line at that speed, so a bot errs toward arriving late. A
battleground bot's trip ends at the first contact point, 0.6 of the way to the central keep less the patrol and
scan radii. The think wake brings a standing bot's next think to its leave moment.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

Expected: `2 files changed, 263 insertions(+)`.

---

### Task 3: Note a release; end a wait at a death or a player's invite

**Files:**
- Modify: `source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs` (add `Note`, `Died` and `JoinedGroup`, with a
  private `Latch`, at the end of the class `RpTimerWait`)
- Modify: `source/server/Tests/UnitTests/UT_RpTimerWait.cs` (32 tests at the class's end, with the values and helpers
  they share)
- Test: `source/server/Tests/UnitTests/UT_RpTimerWait.cs`

**Spec:** 2.4 (the marker, the latch, what ends a wait), 3.5 (hook 3's rules), 3.7 (the `Dying` handler), 3.8 (the
player-group handler), section 6 (off), 7.1, 10.1 ("Note (hook 3)", "Died (3.7)", "Player group (3.8)").

**Interfaces:**
- Consumes: Task 1's types (`RpWaitMarker`, `RpWaitPhase`, `RpWaitCase`, `RpWaitAction`, `RpWaitReason`,
  `RpWaitChange` with `Keep` and `Changes`, `RpWaitSlot` with `Current`, `TrySwap` and `Apply`); Task 2's class
  `RpTimerWait` (the new members go after `ThinkWakeMilliseconds`, its last); upstream's `eAutonomousObjectiveKind`
  (`DOL.GS`, `bots/autonomous/AutonomousObjectiveAssignments.cs:14-21`: `SoloPve`, `GroupPve`, `RvR`,
  `Battleground`). In the tests: Task 1's `Bind`, `Released()` and `SlotWith(...)`, Task 2's `DeathTick`.
- Produces, in `public static class RpTimerWait`:
  - `public static RpWaitChange Note(bool enabled, RpWaitMarker marker, int deathCount, bool alive, bool returning,
    eAutonomousObjectiveKind goal, ushort region, Vector3 position, string assignmentId, bool inGroup,
    bool forceCommitted, bool musterOrder)` (hook 3, through Task 9's `RpTimerWaitScript.NoteRelease`)
  - `public static RpWaitChange Died(RpWaitMarker marker, int deathCount)` (Task 9's `Dying` handler)
  - `public static RpWaitChange JoinedGroup(RpWaitMarker marker, int deathCount, bool leaderIsPlayer)` (Task 9's
    `MemberJoined` handler)
  - `private static RpWaitChange Latch(RpWaitMarker marker, RpWaitAction action, RpWaitReason reason)`: the marker
    read, latched Left, with the change's action and reason (Tasks 4 and 5 may use it)

- [ ] **Step 1: Write the failing tests.** Add them at the end of the class in `UT_RpTimerWait.cs`, after Task 2's
last test, with the values and helpers they share: the bot's RvR assignment id, its realm's arrival point in
Thidranki and a slot 160 from it, a warband slot and session id; a wait running for each case; the previous death's
marker; hook 3's two kinds of turn (the first after a release, and a later one); and three checks of a change (a new
Released marker, a latch, nothing written). Hook 3's test of another assignment or region is named
`AnotherAssignmentOrRegionEndsAWaitAtHook3`, because Task 4 adds `AnotherAssignmentOrRegionEndsAWait` for `Decide`:

```bash
python3 /tmp/hdc-edit.py source/server/Tests/UnitTests/UT_RpTimerWait.cs <<'EDIT'
<<<<<<< OLD
        Assert.That(RpTimerWait.HiberniaFrontier, Is.EqualTo(200));
    }
}
=======
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
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/Tests/UnitTests/UT_RpTimerWait.cs (1 block(s))`.

- [ ] **Step 2: Run them and watch them fail.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWait."`
Expected: the build fails (exit code 1) and no test runs. 15 errors, every one in the new tests and every one
`CS0117`, a member missing from the class `RpTimerWait`: 4 naming `Note`, 6 `Died` and 5 `JoinedGroup`, each with the
file's absolute path and the project at the end of the line. The first of each:

```
source/server/Tests/UnitTests/UT_RpTimerWait.cs(357,21): error CS0117: 'RpTimerWait' does not contain a definition for 'Note'
source/server/Tests/UnitTests/UT_RpTimerWait.cs(567,35): error CS0117: 'RpTimerWait' does not contain a definition for 'Died'
source/server/Tests/UnitTests/UT_RpTimerWait.cs(624,35): error CS0117: 'RpTimerWait' does not contain a definition for 'JoinedGroup'
```

and the last:

```
source/server/Tests/UnitTests/UT_RpTimerWait.cs(652,32): error CS0117: 'RpTimerWait' does not contain a definition for 'JoinedGroup'
```

- [ ] **Step 3: Implement.** Add the members after `ThinkWakeMilliseconds`, before the class's closing brace, with
exactly the code below, each under its rule comment. A private `Latch` builds every Left change: the marker read
`with { Phase = Left }`, a new marker (the slot compares by reference), every other value kept. `Note` takes a
Waiting marker for this death first, whether the release flag is still up or not (rule 2): the switch, then the
assignment id and the region, then a warband marker with no group, then the realm's call by case (a frontier solo's
committed force; a siege or warband member's muster order); otherwise it keeps the marker. Only then a release (alive,
flag up) on an RvR or Battleground goal, with the switch on and no marker for this death, writes a Released marker
over whatever it read (null, or an older death's), with no log action. `Died` latches only a marker for an older death
(the count is raised at GB:953, before `Dying` fires), and `JoinedGroup` only one for this death with a player
leading; for both a Waiting marker logs its leave, a Released one is latched with no line, and anything else is kept.

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs <<'EDIT'
<<<<<<< OLD
        return wake < standardInterval ? (int)wake : standardInterval;
    }
}
=======
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
}
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs (1 block(s))`.

- [ ] **Step 4: Run them and watch them pass.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWait."`
Expected: `Passed!  - Failed:     0, Passed:    62, Skipped:     0, Total:    62` (exit code 0; no warning names
`RpTimerWait.cs` or `UT_RpTimerWait.cs`). 62 = Tasks 1-2's 30 + this task's 32: 14 `[Test]` methods and 18
`[TestCase]` rows (`AReleaseOnAnRvrOrBattlegroundGoalIsNoted` 2, `AReleaseOnAPveGoalIsNotNoted` 2,
`NoNoteWhenResurrectedOrDead` 2, `AnotherAssignmentOrRegionEndsAWaitAtHook3` 4, `AWaitWithNothingChangedIsUnchanged`
4, `KilledWhileWaitingEndsTheWait` 4).

Run: `git diff --stat`
Expected: only the two files, `RpTimerWait.cs` with 72 lines added and `UT_RpTimerWait.cs` with 332, then
`2 files changed, 404 insertions(+)`.

- [ ] **Step 5: Commit.**

```bash
git add source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs source/server/Tests/UnitTests/UT_RpTimerWait.cs
git commit -F - <<'EOF'
feat(rp-wait): note a release, and end a wait at a death or a player's invite

Hook 3's rules: a release on an RvR or battleground goal gets a Released marker for its death; a running wait ends
when the switch goes off, the assignment or region changes, a warband marker has no group, or the realm calls the
bot (a committed frontier force, a muster order). A death ends a running wait, and a player's invite ends a wait or
a release, so a bot resurrected or dropped later never inherits the old wait.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

Expected: `2 files changed, 404 insertions(+)`.

---

### Task 4: The first look and the wait (hooks 1-2's decision)

**Files:**
- Modify: `source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs` (add `WaitSpot` and `Decide`, with three
  private builders of a decision, at the end of the class `RpTimerWait`)
- Modify: `source/server/Tests/UnitTests/UT_RpTimerWait.cs` (52 tests at the class's end, with the values and helpers
  they share)
- Test: `source/server/Tests/UnitTests/UT_RpTimerWait.cs`

**Spec:** 2.3 (wait or go), 2.4 (the marker, the latch, what ends a wait), 3.1-3.4 (the first looks, the trip
targets, the drafted warband's Convert), section 4 (walk back), section 5 (relics), 7.1, 10.1 ("Decide (hooks 1-2)"
and Died's "Decide ignores it").

**Interfaces:**
- Consumes: Task 1's types (`RpWaitMarker`, `RpWaitPhase`, `RpWaitCase`, `RpWaitAction`, `RpWaitReason`,
  `RpWaitVerdict`, `RpWaitLook`, `RpWaitDecision`, `RpWaitSlot` with `Current`, `TrySwap` and `Apply`); Task 2's
  `RpTimerWait.Distance2D` and the constants `BindGate` (750), `ArrivalGate` (2,500), `SlotGate` (200),
  `WalkBackBeyond` (200) and `SpotTolerance` (48); Task 3's `Note` and `Died` (in the tests only; the new members go
  after `JoinedGroup`, the class's last). In the tests: Task 1's `Bind`, `Released()` and `SlotWith(...)`; Task 2's
  `DeathTick`; Task 3's `RvrAssignment`, `Thidranki`, `AlbionArrival`, `AlbionArrivalSlot`, `BorderKeepSlot`,
  `WarbandSession`, `Waiting(RpWaitCase)`, `PreviousDeathsMarker()` and `ReleaseTurn(...)`.
- Produces, in `public static class RpTimerWait`:
  - `public static Vector3 WaitSpot(RpWaitMarker marker, RpWaitLook look)` (Task 11's hooks: where the trip starts)
  - `public static RpWaitDecision Decide(RpWaitMarker marker, int deathCount, RpWaitLook look, long timeLeft,
    long tripMilliseconds, long now)` (Task 11's `RpTimerWaitBattleground` and `RpTimerWaitRvr`, whose `RpWaitAct`
    carries the decision out)
  - `private static RpWaitDecision Ignore(RpWaitMarker marker)`, `private static RpWaitDecision Skip(RpWaitMarker
    marker, RpWaitCase hookCase, RpWaitReason reason, RpWaitAction action = RpWaitAction.Skip)` and `private static
    RpWaitDecision Leave(RpWaitMarker marker, RpWaitReason reason)`: `Decide`'s Ignore (the marker read kept), Skip
    (latched Left with the hook's case) and Leave (latched Left)

- [ ] **Step 1: Write the failing tests.** Add them at the end of the class in `UT_RpTimerWait.cs`, after Task 3's
last test, with the values and helpers they share: a hook turn's clock (`Now`, 60 s after the death, with 240 s left
and a trip of 42,832 ms); Albion's capital anchor in Camelot; a battleground bot's Released marker (released in
Camelot, back by the teleporter); what a hook sees on a turn where nothing has changed (`Look`, per case, each
input overridable); the decision on that turn (`Turn`, through which every test calls `Decide`); and five checks of a
decision (Ignore, a first look's Skip and Start, Hold, Leave). The `Decide` test of the region and the assignment
is `AnotherAssignmentOrRegionEndsAWait` (Task 3 named its own hook 3 test
`AnotherAssignmentOrRegionEndsAWaitAtHook3`):

```bash
python3 /tmp/hdc-edit.py source/server/Tests/UnitTests/UT_RpTimerWait.cs <<'EDIT'
<<<<<<< OLD
        AssertKept(RpTimerWait.JoinedGroup(null, 3, true), null);
    }
}
=======
        AssertKept(RpTimerWait.JoinedGroup(null, 3, true), null);
    }

    // A hook 1-2 turn 60 s after the death: 240 s left on the timer (2.1), against a trip of 42,832 ms (Midgard's 8,181
    // from its arrival point to first contact at 191 units/s, 3.1).
    private const long Now = DeathTick + 60_000;
    private const long TimeLeft = 240_000;
    private const long Trip = 42_832;

    // Albion's capital anchor in Camelot (AutonomousStuckWatchdog.CapitalFor), where an Albion bot with no bind of its
    // realm near its death releases (GB:1084-1089).
    private const ushort CamelotRegion = 10;
    private static readonly Vector3 Camelot = new(35_990, 30_298, 8_000);

    // The battleground bot of Waiting(Battleground), released for death count 3 outside the battleground (here in
    // Camelot) and back through the teleporter, which lands it on slot 0, its realm's arrival point
    // (TownTeleport.cs:139-142).
    private static RpWaitMarker ReleasedForTheBattleground() =>
        new(3, RpWaitPhase.Released, RpWaitCase.None, CamelotRegion, Camelot, CamelotRegion, Camelot,
            "albion-20-12-Battleground", null, null, 0);

    // What hook 1 or 2 sees on a turn where nothing has changed (3.1-3.4): a battleground bot at its slot in Thidranki
    // with its tour's assignment, its realm's arrival point and its slot; otherwise the bot of Released() in the Albion
    // frontier with its RvR assignment, at its bind (a warband member at its slot by the border keep), a siege's event
    // keep rvr-keep-50, and a trip target in its region (hook 2 gives a warband outside battle none). Each test changes
    // what it is about.
    private static RpWaitLook Look(RpWaitCase lookCase, Vector3? position = null, ushort? region = null,
        string assignmentId = null, string eventKeepId = null, bool relic = false, bool? hasTarget = null,
        ushort? targetRegion = null)
    {
        bool battleground = lookCase == RpWaitCase.Battleground;
        ushort here = region ?? (battleground ? Thidranki : (ushort)1);
        Vector3 standing = position ?? (battleground ? AlbionArrivalSlot
            : lookCase == RpWaitCase.Warband ? BorderKeepSlot : Bind);
        return new RpWaitLook(lookCase, here, standing,
            assignmentId ?? (battleground ? "albion-20-12-Battleground" : RvrAssignment),
            eventKeepId ?? (lookCase == RpWaitCase.Siege ? "rvr-keep-50" : null), relic,
            hasTarget ?? lookCase != RpWaitCase.Warband, targetRegion ?? here,
            battleground ? AlbionArrival : default, battleground ? AlbionArrivalSlot : default);
    }

    // Hooks 1-2's decision on that turn, for death count 3; each test sets what it is about.
    private static RpWaitDecision Turn(RpWaitMarker marker, RpWaitLook look, long timeLeft = TimeLeft, long trip = Trip,
        int deathCount = 3) =>
        RpTimerWait.Decide(marker, deathCount, look, timeLeft, trip, Now);

    // Ignore: the marker read is kept (the same reference, null included); no line, and the hook lets the bot go on.
    private static void AssertIgnored(RpWaitDecision decision, RpWaitMarker marker)
    {
        Assert.That(decision.Verdict, Is.EqualTo(RpWaitVerdict.Ignore));
        Assert.That(decision.Reason, Is.EqualTo(RpWaitReason.None));
        Assert.That(decision.Before, Is.SameAs(marker));
        Assert.That(decision.Next, Is.SameAs(marker));
        Assert.That(decision.Action, Is.EqualTo(RpWaitAction.None));
        Assert.That(decision.WalkBack, Is.False);
    }

    // A first look's Skip: the Released marker read is latched Left (a new marker) with the hook's case stored, with
    // this reason and its skip line (none for a bot already worth points).
    private static void AssertSkipped(RpWaitDecision decision, RpWaitMarker before, RpWaitCase hookCase,
        RpWaitReason reason, RpWaitAction action = RpWaitAction.Skip)
    {
        Assert.That(decision.Verdict, Is.EqualTo(RpWaitVerdict.Skip));
        Assert.That(decision.Reason, Is.EqualTo(reason));
        Assert.That(decision.Before, Is.SameAs(before));
        Assert.That(decision.Next, Is.Not.SameAs(before));
        Assert.That(decision.Next, Is.EqualTo(before with { Phase = RpWaitPhase.Left, Case = hookCase }));
        Assert.That(decision.Action, Is.EqualTo(action));
        Assert.That(decision.WalkBack, Is.False);
    }

    // A first look's Start: the Released marker read becomes this Waiting marker, with its start line.
    private static void AssertStarted(RpWaitDecision decision, RpWaitMarker before, RpWaitMarker expected,
        bool walkBack)
    {
        Assert.That(decision.Verdict, Is.EqualTo(RpWaitVerdict.Start));
        Assert.That(decision.Reason, Is.EqualTo(RpWaitReason.None));
        Assert.That(decision.Before, Is.SameAs(before));
        Assert.That(decision.Next, Is.EqualTo(expected));
        Assert.That(decision.Action, Is.EqualTo(RpWaitAction.Start));
        Assert.That(decision.WalkBack, Is.EqualTo(walkBack));
    }

    // A Hold: the wait goes on with the marker read (the same reference), no line; WalkBack when it must walk back.
    private static void AssertHeld(RpWaitDecision decision, RpWaitMarker marker, bool walkBack)
    {
        Assert.That(decision.Verdict, Is.EqualTo(RpWaitVerdict.Hold));
        Assert.That(decision.Reason, Is.EqualTo(RpWaitReason.None));
        Assert.That(decision.Before, Is.SameAs(marker));
        Assert.That(decision.Next, Is.SameAs(marker));
        Assert.That(decision.Action, Is.EqualTo(RpWaitAction.None));
        Assert.That(decision.WalkBack, Is.EqualTo(walkBack));
    }

    // A Leave: the Waiting marker read is latched Left (a new marker, every other value the same) with this reason and
    // its leave line.
    private static void AssertLeaves(RpWaitDecision decision, RpWaitMarker before, RpWaitReason reason)
    {
        Assert.That(decision.Verdict, Is.EqualTo(RpWaitVerdict.Leave));
        Assert.That(decision.Reason, Is.EqualTo(reason));
        Assert.That(decision.Before, Is.SameAs(before));
        Assert.That(decision.Next, Is.Not.SameAs(before));
        Assert.That(decision.Next, Is.EqualTo(before with { Phase = RpWaitPhase.Left }));
        Assert.That(decision.Action, Is.EqualTo(RpWaitAction.Leave));
        Assert.That(decision.WalkBack, Is.False);
    }

    // 2.4: hooks 1-2 act only on a marker for the death now. No marker (no release noted: a resurrection, a PvE goal,
    // the switch off) or a marker for an older death count is ignored, whatever the hook sees.
    [Test]
    public void NoMarkerOrAnOlderDeathsMarkerIsIgnored()
    {
        AssertIgnored(Turn(null, Look(RpWaitCase.Frontier)), null);
        AssertIgnored(Turn(null, Look(RpWaitCase.Battleground)), null);

        RpWaitMarker[] older =
        {
            PreviousDeathsMarker(),
            Released() with { DeathCount = 2 },
            Waiting(RpWaitCase.Frontier) with { DeathCount = 2 },
            Waiting(RpWaitCase.Siege) with { DeathCount = 2 },
        };
        foreach (RpWaitMarker marker in older)
        {
            AssertIgnored(Turn(marker, Look(RpWaitCase.Frontier)), marker);
            AssertIgnored(Turn(marker, Look(RpWaitCase.Siege), timeLeft: 0), marker);
        }
    }

    // 2.4: the latch. Once a first look has skipped or a wait has ended, nothing the bot sees later for that death
    // stops it again: a trip of 0 (it stands at its target), a new target, a target in another region, or a speed
    // song that shortens the trip.
    [Test]
    public void ALeftMarkerIsIgnoredWhateverChangesNext()
    {
        RpWaitMarker skipped = Released() with { Phase = RpWaitPhase.Left, Case = RpWaitCase.Frontier };
        RpWaitMarker ended = Waiting(RpWaitCase.Siege) with { Phase = RpWaitPhase.Left };
        foreach (RpWaitMarker left in new[] { skipped, ended })
        {
            AssertIgnored(Turn(left, Look(RpWaitCase.Frontier), trip: 0), left);
            AssertIgnored(Turn(left, Look(RpWaitCase.Siege, eventKeepId: "rvr-keep-51")), left);
            AssertIgnored(Turn(left, Look(RpWaitCase.Frontier, targetRegion: 100)), left);
            AssertIgnored(Turn(left, Look(RpWaitCase.Frontier), trip: 30_000), left);
        }

        RpWaitMarker battleground = Waiting(RpWaitCase.Battleground) with { Phase = RpWaitPhase.Left };
        AssertIgnored(Turn(battleground, Look(RpWaitCase.Battleground), trip: 0), battleground);
    }

    // 3.7: the Dying handler latches the marker Left for the old death count, so hooks 1-2 ignore it, with the count
    // now or the one a turn read before the death; and a Start decided from the Released marker before the death then
    // fails its swap, with no start line.
    [Test]
    public void AMarkerLatchedByADeathIsIgnored()
    {
        RpWaitSlot slot = SlotWith(Waiting(RpWaitCase.Frontier));
        slot.Apply(marker => RpTimerWait.Died(marker, 4));
        RpWaitMarker left = slot.Current;
        AssertIgnored(Turn(left, Look(RpWaitCase.Frontier), deathCount: 4), left);
        AssertIgnored(Turn(left, Look(RpWaitCase.Frontier), deathCount: 3), left);

        RpWaitMarker released = ReleasedForTheBattleground();
        RpWaitSlot battleground = SlotWith(released);
        RpWaitDecision start = Turn(released, Look(RpWaitCase.Battleground, position: AlbionArrival));
        Assert.That(start.Verdict, Is.EqualTo(RpWaitVerdict.Start));
        battleground.Apply(marker => RpTimerWait.Died(marker, 4));
        Assert.That(battleground.TrySwap(start.Before, start.Next), Is.False);

        RpWaitMarker latched = battleground.Current;
        Assert.That(latched.Phase, Is.EqualTo(RpWaitPhase.Left));
        AssertIgnored(Turn(latched, Look(RpWaitCase.Battleground, position: AlbionArrival), deathCount: 4), latched);
        AssertIgnored(Turn(latched, Look(RpWaitCase.Battleground, position: AlbionArrival), deathCount: 3), latched);
    }

    // Section 5: a relic carrier, a relic escort, interceptor or picker (a destination rvr-relic-carrier-) and a force
    // in a relic event (a battle with no keep plan, seen as Case Frontier with Relic) never wait, wherever they
    // stand: the relic comes before the region, the target, the gate and the trip.
    [Test]
    public void ARelicSkipsTheFirstLook()
    {
        RpWaitMarker released = Released();
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier, relic: true)), released, RpWaitCase.Frontier,
            RpWaitReason.Relic);
        AssertSkipped(Turn(released, Look(RpWaitCase.Siege, relic: true)), released, RpWaitCase.Siege,
            RpWaitReason.Relic);
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier, position: new Vector3(Bind.X + 3_000, Bind.Y, Bind.Z),
            region: 100, relic: true, hasTarget: false)), released, RpWaitCase.Frontier, RpWaitReason.Relic);
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier, relic: true), timeLeft: Trip), released,
            RpWaitCase.Frontier, RpWaitReason.Relic);
    }

    // 3.2, 3.3: a frontier or siege first look happens in the release region, with a target there. A bot released in
    // its capital (here Camelot) waits nowhere: not later in a frontier, nor at its capital bind with a target in a
    // frontier. A battleground bot has no such check: it always released outside and came in by the teleporter.
    [Test]
    public void AnotherRegionThanTheReleasePointOrTheTargetSkips()
    {
        RpWaitMarker inCamelot = Released() with
        {
            ReleaseRegion = CamelotRegion, ReleasePoint = Camelot, Region = CamelotRegion, Spot = Camelot,
        };
        AssertSkipped(Turn(inCamelot, Look(RpWaitCase.Frontier, region: 100)), inCamelot, RpWaitCase.Frontier,
            RpWaitReason.OtherRegion);
        AssertSkipped(Turn(inCamelot, Look(RpWaitCase.Siege, region: 100)), inCamelot, RpWaitCase.Siege,
            RpWaitReason.OtherRegion);
        AssertSkipped(Turn(inCamelot, Look(RpWaitCase.Frontier, position: Camelot, region: CamelotRegion,
            targetRegion: 100)), inCamelot, RpWaitCase.Frontier, RpWaitReason.OtherRegion);

        RpWaitMarker released = Released();
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier, targetRegion: 100)), released, RpWaitCase.Frontier,
            RpWaitReason.OtherRegion);
        AssertSkipped(Turn(released, Look(RpWaitCase.Siege, targetRegion: 200)), released, RpWaitCase.Siege,
            RpWaitReason.OtherRegion);

        RpWaitMarker battleground = ReleasedForTheBattleground();
        Assert.That(Turn(battleground, Look(RpWaitCase.Battleground, position: AlbionArrival)).Verdict,
            Is.EqualTo(RpWaitVerdict.Start));
    }

    // 3.1-3.3: no trip target (no destination nor death spot for a frontier solo, no event keep for a siege, no central
    // keep for a battleground): no wait. Before the gate: far from its bind with no target is no-target.
    [Test]
    public void NoTargetSkips()
    {
        RpWaitMarker released = Released();
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier, hasTarget: false)), released, RpWaitCase.Frontier,
            RpWaitReason.NoTarget);
        AssertSkipped(Turn(released, Look(RpWaitCase.Siege, hasTarget: false)), released, RpWaitCase.Siege,
            RpWaitReason.NoTarget);
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier, position: new Vector3(Bind.X, Bind.Y + 3_000, Bind.Z),
            hasTarget: false)), released, RpWaitCase.Frontier, RpWaitReason.NoTarget);

        RpWaitMarker battleground = ReleasedForTheBattleground();
        AssertSkipped(Turn(battleground, Look(RpWaitCase.Battleground, position: AlbionArrival, hasTarget: false)),
            battleground, RpWaitCase.Battleground, RpWaitReason.NoTarget);
    }

    // 3.1, 3.2: the first look's gate, horizontal (a bot 400 higher counts the same): within 2,500 of its realm's
    // arrival point in a battleground, within 750 of its release point (a bind) otherwise. Farther: moved-away.
    [TestCase(RpWaitCase.Battleground, 2_500f, true)]
    [TestCase(RpWaitCase.Battleground, 2_501f, false)]
    [TestCase(RpWaitCase.Frontier, 750f, true)]
    [TestCase(RpWaitCase.Frontier, 751f, false)]
    [TestCase(RpWaitCase.Siege, 750f, true)]
    [TestCase(RpWaitCase.Siege, 751f, false)]
    public void OutsideTheFirstLookGateSkips(RpWaitCase lookCase, float away, bool starts)
    {
        bool battleground = lookCase == RpWaitCase.Battleground;
        RpWaitMarker released = battleground ? ReleasedForTheBattleground() : Released();
        Vector3 gate = battleground ? AlbionArrival : Bind;
        var position = new Vector3(gate.X, gate.Y - away, gate.Z + 400);
        RpWaitDecision decision = Turn(released, Look(lookCase, position: position));

        if (starts)
        {
            Assert.That(decision.Verdict, Is.EqualTo(RpWaitVerdict.Start));
            Assert.That(decision.Next.Spot, Is.EqualTo(battleground ? AlbionArrivalSlot : Bind));
            Assert.That(decision.WalkBack, Is.True);
        }
        else
        {
            AssertSkipped(decision, released, lookCase, RpWaitReason.MovedAway);
        }
    }

    // 2.3: a bot whose time left is no more than its trip goes at once (equal is enough); 1 ms more and it waits. With
    // no speed (a trip of long.MaxValue) it never waits.
    [Test]
    public void TimeLeftWithinTheTripSkips()
    {
        RpWaitMarker released = Released();
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier), timeLeft: Trip), released, RpWaitCase.Frontier,
            RpWaitReason.Trip);
        AssertSkipped(Turn(released, Look(RpWaitCase.Siege), timeLeft: 10_000), released, RpWaitCase.Siege,
            RpWaitReason.Trip);
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier), trip: long.MaxValue), released, RpWaitCase.Frontier,
            RpWaitReason.Trip);
        Assert.That(Turn(released, Look(RpWaitCase.Frontier), timeLeft: Trip + 1).Verdict,
            Is.EqualTo(RpWaitVerdict.Start));

        RpWaitMarker battleground = ReleasedForTheBattleground();
        AssertSkipped(Turn(battleground, Look(RpWaitCase.Battleground, position: AlbionArrival), timeLeft: Trip),
            battleground, RpWaitCase.Battleground, RpWaitReason.Trip);
    }

    // 3.4, applied to the first look: a bot already worth points (time left 0) is latched Skip(Trip) with no line, as
    // the gate latches a Released member worth points, before any other check (a relic, another region, no target).
    [Test]
    public void AReleasedBotAlreadyWorthSkipsWithNoLine()
    {
        RpWaitMarker released = Released();
        AssertSkipped(Turn(released, Look(RpWaitCase.Frontier), timeLeft: 0), released, RpWaitCase.Frontier,
            RpWaitReason.Trip, RpWaitAction.None);
        AssertSkipped(Turn(released, Look(RpWaitCase.Siege, region: 100, relic: true, hasTarget: false), timeLeft: 0),
            released, RpWaitCase.Siege, RpWaitReason.Trip, RpWaitAction.None);

        RpWaitMarker battleground = ReleasedForTheBattleground();
        AssertSkipped(Turn(battleground, Look(RpWaitCase.Battleground, position: AlbionArrival), timeLeft: 0),
            battleground, RpWaitCase.Battleground, RpWaitReason.Trip, RpWaitAction.None);
    }

    // 3.1-3.3: a first look that passes every check starts a wait: a battleground bot at its slot, a frontier solo or a
    // siege member at its release point (its bind), with the region, the assignment id it has now (here a newer one
    // than at its release) and Started = now; it walks to its spot when more than 48 from it.
    [TestCase(RpWaitCase.Battleground, 0f, true)]
    [TestCase(RpWaitCase.Frontier, 0f, false)]
    [TestCase(RpWaitCase.Frontier, 300f, true)]
    [TestCase(RpWaitCase.Siege, 0f, false)]
    [TestCase(RpWaitCase.Siege, 300f, true)]
    public void TheFirstLookStartsAWait(RpWaitCase lookCase, float east, bool walkBack)
    {
        bool battleground = lookCase == RpWaitCase.Battleground;
        RpWaitMarker released = battleground ? ReleasedForTheBattleground() : Released();
        Vector3 landed = battleground ? AlbionArrival : Bind;
        string assignmentId = battleground ? "albion-20-13-Battleground" : "albion-40-13-RvR";
        RpWaitLook look = Look(lookCase, position: new Vector3(landed.X + east, landed.Y, landed.Z),
            assignmentId: assignmentId);

        AssertStarted(Turn(released, look), released, released with
        {
            Phase = RpWaitPhase.Waiting,
            Case = lookCase,
            Region = battleground ? Thidranki : (ushort)1,
            Spot = battleground ? AlbionArrivalSlot : Bind,
            AssignmentId = assignmentId,
            EventKeepId = lookCase == RpWaitCase.Siege ? "rvr-keep-50" : null,
            Started = Now,
        }, walkBack);
    }

    // 3.1: the teleporter lands a solo bot on slot 0, the arrival point itself, and slots 1 and 2 are 160 and 189
    // from it (AutonomousTownTeleporters.cs:148-152). A Start walks to its slot when more than 48 from it (IssuePath's
    // own arrival radius, WBC:5176-5180), not only past the 200 of a wait's later turns, where it holds.
    [TestCase(160f, true)]
    [TestCase(49f, true)]
    [TestCase(48f, false)]
    [TestCase(20f, false)]
    public void TheFirstLookWalksToABattlegroundSlotOnly160Away(float away, bool walkBack)
    {
        RpWaitMarker released = ReleasedForTheBattleground();
        RpWaitLook look = Look(RpWaitCase.Battleground,
            position: new Vector3(AlbionArrivalSlot.X - away, AlbionArrivalSlot.Y, AlbionArrivalSlot.Z));

        RpWaitDecision start = Turn(released, look);
        Assert.That(start.Verdict, Is.EqualTo(RpWaitVerdict.Start));
        Assert.That(start.Next.Spot, Is.EqualTo(AlbionArrivalSlot));
        Assert.That(start.WalkBack, Is.EqualTo(walkBack));

        AssertHeld(Turn(start.Next, look), start.Next, false);
    }

    // 3.3: a siege wait stores the event keep (_rvrDestination.Id) its trip goes to, so a later draft to another keep
    // ends it; a frontier or battleground wait stores none, even from a look that carries one. No session id: a bot
    // released alone.
    [Test]
    public void ASiegeStartStoresTheEventKeep()
    {
        RpWaitMarker released = Released();
        RpWaitDecision siege = Turn(released, Look(RpWaitCase.Siege, eventKeepId: "rvr-keep-51"));
        Assert.That(siege.Verdict, Is.EqualTo(RpWaitVerdict.Start));
        Assert.That(siege.Next.Case, Is.EqualTo(RpWaitCase.Siege));
        Assert.That(siege.Next.EventKeepId, Is.EqualTo("rvr-keep-51"));
        Assert.That(siege.Next.SessionId, Is.Null);

        RpWaitDecision frontier = Turn(released, Look(RpWaitCase.Frontier, eventKeepId: "rvr-keep-51"));
        Assert.That(frontier.Verdict, Is.EqualTo(RpWaitVerdict.Start));
        Assert.That(frontier.Next.EventKeepId, Is.Null);

        RpWaitMarker inBattleground = ReleasedForTheBattleground();
        RpWaitDecision battleground = Turn(inBattleground,
            Look(RpWaitCase.Battleground, position: AlbionArrival, eventKeepId: "rvr-keep-51"));
        Assert.That(battleground.Verdict, Is.EqualTo(RpWaitVerdict.Start));
        Assert.That(battleground.Next.EventKeepId, Is.Null);
    }

    // 3.4: a warband regrouping outside a siege battle is the warband gate's (hook 4). Hook 2 neither starts
    // nor skips its first look, whatever it sees: worth already, within the trip, far from its bind, a relic (the
    // gate's own relic check says go).
    [Test]
    public void AReleasedWarbandMemberOutsideBattleIsTheGates()
    {
        RpWaitMarker released = Released();
        AssertIgnored(Turn(released, Look(RpWaitCase.Warband)), released);
        AssertIgnored(Turn(released, Look(RpWaitCase.Warband), timeLeft: 0), released);
        AssertIgnored(Turn(released, Look(RpWaitCase.Warband), timeLeft: Trip), released);
        AssertIgnored(Turn(released, Look(RpWaitCase.Warband, position: new Vector3(Bind.X, Bind.Y + 3_000, Bind.Z))),
            released);
        AssertIgnored(Turn(released, Look(RpWaitCase.Warband, relic: true)), released);
    }

    // 2.3: a wait holds while time left is more than the trip and leaves (due) on the first turn where it is no more,
    // each bot at its own moment, a battleground bot too; with no speed it leaves at once.
    [TestCase(RpWaitCase.Frontier)]
    [TestCase(RpWaitCase.Siege)]
    [TestCase(RpWaitCase.Battleground)]
    public void AWaitHoldsUntilTimeLeftEqualsTheTrip(RpWaitCase waitCase)
    {
        RpWaitMarker waiting = Waiting(waitCase);
        AssertHeld(Turn(waiting, Look(waitCase), timeLeft: Trip + 1), waiting, false);
        AssertLeaves(Turn(waiting, Look(waitCase), timeLeft: Trip), waiting, RpWaitReason.Due);
        AssertLeaves(Turn(waiting, Look(waitCase), timeLeft: 0), waiting, RpWaitReason.Due);
        AssertLeaves(Turn(waiting, Look(waitCase), trip: long.MaxValue), waiting, RpWaitReason.Due);
    }

    // Section 4, 2.4: a fight never ends a wait. Afterwards a bot more than 200 from its spot holds and walks back,
    // from any distance; within 200 it holds where it is. Horizontal: 400 higher counts the same.
    [TestCase(200f, false)]
    [TestCase(201f, true)]
    [TestCase(3_000f, true)]
    public void AWaitFarFromItsSpotHoldsAndWalksBack(float away, bool walkBack)
    {
        foreach (RpWaitCase waitCase in new[] { RpWaitCase.Frontier, RpWaitCase.Siege, RpWaitCase.Battleground })
        {
            RpWaitMarker waiting = Waiting(waitCase);
            var position = new Vector3(waiting.Spot.X, waiting.Spot.Y + away, waiting.Spot.Z + 400);
            AssertHeld(Turn(waiting, Look(waitCase, position: position)), waiting, walkBack);
        }
    }

    // 2.4: a new assignment id or another region than the wait's ends it (hook 3 usually first), whatever the case and
    // before anything else the hook sees (a warband's look included: it is the gate's only while nothing changed).
    [TestCase(RpWaitCase.Frontier)]
    [TestCase(RpWaitCase.Siege)]
    [TestCase(RpWaitCase.Warband)]
    [TestCase(RpWaitCase.Battleground)]
    public void AnotherAssignmentOrRegionEndsAWait(RpWaitCase waitCase)
    {
        RpWaitMarker waiting = Waiting(waitCase);
        AssertLeaves(Turn(waiting, Look(waitCase, assignmentId: "albion-40-13-RvR")), waiting, RpWaitReason.Changed);
        AssertLeaves(Turn(waiting, Look(waitCase, region: CamelotRegion)), waiting, RpWaitReason.Changed);
        AssertLeaves(Turn(waiting, Look(waitCase, assignmentId: "albion-40-13-RvR", relic: true, hasTarget: false),
            timeLeft: 0), waiting, RpWaitReason.Changed);
    }

    // 2.4, 3.4: a case change seen by hooks 1-2 ends a wait (changed): a frontier wait that sees a siege (hook 3 has
    // usually ended a drafted solo's wait first, as called), a siege wait that sees the frontier, a frontier or siege
    // wait that sees a warband outside battle, and a warband wait that hook 2 sees as neither a warband nor a siege.
    [TestCase(RpWaitCase.Frontier, RpWaitCase.Siege)]
    [TestCase(RpWaitCase.Siege, RpWaitCase.Frontier)]
    [TestCase(RpWaitCase.Frontier, RpWaitCase.Warband)]
    [TestCase(RpWaitCase.Siege, RpWaitCase.Warband)]
    [TestCase(RpWaitCase.Warband, RpWaitCase.Frontier)]
    public void ACaseChangeEndsAWait(RpWaitCase waitCase, RpWaitCase lookCase)
    {
        RpWaitMarker waiting = Waiting(waitCase);
        AssertLeaves(Turn(waiting, Look(lookCase, position: waiting.Spot)), waiting, RpWaitReason.Changed);
    }

    // Section 5: a relic ends a wait, before the case, the target and the time: a relic carrier or escort
    // (the wait's own case with Relic), a siege member caught in a relic event (a battle with no keep plan: Case
    // Frontier with Relic), and a waiting warband member that hook 2 reaches as a relic carrier (WBC:459).
    [Test]
    public void ARelicEndsAWait()
    {
        foreach (RpWaitCase waitCase in new[] { RpWaitCase.Frontier, RpWaitCase.Siege })
        {
            RpWaitMarker waiting = Waiting(waitCase);
            AssertLeaves(Turn(waiting, Look(waitCase, relic: true)), waiting, RpWaitReason.Relic);
            AssertLeaves(Turn(waiting, Look(waitCase, relic: true, hasTarget: false), timeLeft: 0), waiting,
                RpWaitReason.Relic);
        }

        RpWaitMarker siege = Waiting(RpWaitCase.Siege);
        AssertLeaves(Turn(siege, Look(RpWaitCase.Frontier, relic: true)), siege, RpWaitReason.Relic);

        RpWaitMarker held = Waiting(RpWaitCase.Warband);
        AssertLeaves(Turn(held, Look(RpWaitCase.Warband, relic: true)), held, RpWaitReason.Relic);
    }

    // 2.4: a target gone or in another region ends a wait (no-target, other-region), before its time: a target in
    // another region with time left within the trip logs other-region, not due. A drafted warband member too.
    [TestCase(RpWaitCase.Frontier, RpWaitCase.Frontier)]
    [TestCase(RpWaitCase.Siege, RpWaitCase.Siege)]
    [TestCase(RpWaitCase.Battleground, RpWaitCase.Battleground)]
    [TestCase(RpWaitCase.Warband, RpWaitCase.Siege)]
    public void AGoneTargetEndsAWait(RpWaitCase waitCase, RpWaitCase lookCase)
    {
        RpWaitMarker waiting = Waiting(waitCase);
        AssertLeaves(Turn(waiting, Look(lookCase, position: waiting.Spot, hasTarget: false)), waiting,
            RpWaitReason.NoTarget);
        AssertLeaves(Turn(waiting, Look(lookCase, position: waiting.Spot, targetRegion: 100)), waiting,
            RpWaitReason.OtherRegion);
        AssertLeaves(Turn(waiting, Look(lookCase, position: waiting.Spot, targetRegion: 100), timeLeft: 0), waiting,
            RpWaitReason.OtherRegion);
    }

    // 3.3: the draft can move a defence force to another defence (ELD:294-307) with no muster order for hook 3 to see:
    // hook 2 sees another event keep than the stored one and ends the wait as called, in its region or another (the
    // keep comes before the region). A warband member converted at its slot likewise. The same keep holds.
    [Test]
    public void ASiegeWaitEndsWhenTheDraftMovesItToAnotherKeep()
    {
        RpWaitMarker siege = Waiting(RpWaitCase.Siege);
        AssertLeaves(Turn(siege, Look(RpWaitCase.Siege, eventKeepId: "rvr-keep-51")), siege, RpWaitReason.Called);
        AssertLeaves(Turn(siege, Look(RpWaitCase.Siege, region: 100, eventKeepId: "rvr-keep-51")), siege,
            RpWaitReason.Called);
        AssertHeld(Turn(siege, Look(RpWaitCase.Siege)), siege, false);

        RpWaitMarker converted =
            Turn(Waiting(RpWaitCase.Warband), Look(RpWaitCase.Siege, position: BorderKeepSlot)).Next;
        Assert.That(converted.Case, Is.EqualTo(RpWaitCase.Siege));
        AssertLeaves(Turn(converted, Look(RpWaitCase.Siege, position: BorderKeepSlot, eventKeepId: "rvr-keep-51")),
            converted, RpWaitReason.Called);
        AssertHeld(Turn(converted, Look(RpWaitCase.Siege, position: BorderKeepSlot)), converted, false);
    }

    // 3.4 "Drafted mid-wait": a held warband drafted into a battle reaches hook 2 as a siege. Within 200 of its slot in
    // the stored region it stays Waiting, as a siege member at its slot: the event keep stored; the session id, region,
    // spot and assignment id kept; Started now. One Convert (leave reason=battle, then start case=siege), no walk.
    [Test]
    public void AWaitingWarbandDraftedIntoABattleConvertsAtItsSlot()
    {
        RpWaitMarker held = Waiting(RpWaitCase.Warband);
        foreach (float away in new[] { 0f, 120f, 200f })
        {
            RpWaitLook look = Look(RpWaitCase.Siege,
                position: new Vector3(BorderKeepSlot.X, BorderKeepSlot.Y - away, BorderKeepSlot.Z),
                eventKeepId: "rvr-keep-51");

            RpWaitDecision decision = Turn(held, look);

            Assert.That(decision.Verdict, Is.EqualTo(RpWaitVerdict.Convert));
            Assert.That(decision.Reason, Is.EqualTo(RpWaitReason.Battle));
            Assert.That(decision.Action, Is.EqualTo(RpWaitAction.Convert));
            Assert.That(decision.Before, Is.SameAs(held));
            Assert.That(decision.Next, Is.EqualTo(held with
            {
                Case = RpWaitCase.Siege, EventKeepId = "rvr-keep-51", Started = Now,
            }));
            Assert.That(decision.Next.Phase, Is.EqualTo(RpWaitPhase.Waiting));
            Assert.That(decision.Next.Spot, Is.EqualTo(BorderKeepSlot));
            Assert.That(decision.Next.SessionId, Is.EqualTo(WarbandSession));
            Assert.That(decision.WalkBack, Is.False);
        }
    }

    // 3.4: farther than 200 from its slot, or with time left no more than its trip to the event keep, a drafted
    // member's wait ends (moved-away, due; the slot comes first) and it goes in as today.
    [Test]
    public void ADraftedWarbandMemberAwayFromItsSlotOrDueLeaves()
    {
        RpWaitMarker held = Waiting(RpWaitCase.Warband);
        var away300 = new Vector3(BorderKeepSlot.X, BorderKeepSlot.Y - 300, BorderKeepSlot.Z);
        var away201 = new Vector3(BorderKeepSlot.X, BorderKeepSlot.Y - 201, BorderKeepSlot.Z);
        AssertLeaves(Turn(held, Look(RpWaitCase.Siege, position: away300)), held, RpWaitReason.MovedAway);
        AssertLeaves(Turn(held, Look(RpWaitCase.Siege, position: away201)), held, RpWaitReason.MovedAway);
        AssertLeaves(Turn(held, Look(RpWaitCase.Siege, position: BorderKeepSlot), timeLeft: Trip), held,
            RpWaitReason.Due);
        AssertLeaves(Turn(held, Look(RpWaitCase.Siege, position: away300), timeLeft: Trip), held,
            RpWaitReason.MovedAway);
    }

    // 3.4: a waiting warband member that hook 2 sees as a warband outside battle is the gate's: Ignore, whatever
    // its time, distance or target (the regroup walks it back to its slot; the gate opens it).
    [Test]
    public void AWaitingWarbandMarkerOutsideBattleIsTheGates()
    {
        RpWaitMarker held = Waiting(RpWaitCase.Warband);
        AssertIgnored(Turn(held, Look(RpWaitCase.Warband)), held);
        AssertIgnored(Turn(held, Look(RpWaitCase.Warband), timeLeft: 0), held);
        AssertIgnored(Turn(held, Look(RpWaitCase.Warband), timeLeft: Trip), held);
        AssertIgnored(Turn(held, Look(RpWaitCase.Warband,
            position: new Vector3(BorderKeepSlot.X, BorderKeepSlot.Y - 3_000, BorderKeepSlot.Z))), held);
    }

    // 3.4: a member whose marker is still Released when its warband is drafted (the gate had not held it yet) gets the
    // plain siege first look at its bind: at a slot 3,000 from it, moved-away; at its bind, a siege wait there.
    [Test]
    public void AReleasedWarbandMemberInABattleFarFromItsBindSkips()
    {
        RpWaitMarker released = Released();
        AssertSkipped(Turn(released, Look(RpWaitCase.Siege, position: new Vector3(Bind.X, Bind.Y + 3_000, Bind.Z))),
            released, RpWaitCase.Siege, RpWaitReason.MovedAway);

        RpWaitDecision atBind = Turn(released, Look(RpWaitCase.Siege));
        Assert.That(atBind.Verdict, Is.EqualTo(RpWaitVerdict.Start));
        Assert.That(atBind.Next.Spot, Is.EqualTo(Bind));
        Assert.That(atBind.Next.SessionId, Is.Null);
    }

    // 2.4: only a new release after a new death resets the latch. A wait for death 3 starts and ends; hook 3 writes
    // Released for death 4 over its Left marker, and the next first look starts a new wait.
    [Test]
    public void ANewDeathAndReleaseStartsAgain()
    {
        RpWaitSlot slot = SlotWith(Released());
        RpWaitDecision start = Turn(slot.Current, Look(RpWaitCase.Frontier));
        Assert.That(start.Verdict, Is.EqualTo(RpWaitVerdict.Start));
        Assert.That(slot.TrySwap(start.Before, start.Next), Is.True);
        RpWaitDecision due = Turn(slot.Current, Look(RpWaitCase.Frontier), timeLeft: Trip);
        Assert.That(due.Verdict, Is.EqualTo(RpWaitVerdict.Leave));
        Assert.That(slot.TrySwap(due.Before, due.Next), Is.True);
        AssertIgnored(Turn(slot.Current, Look(RpWaitCase.Frontier)), slot.Current);

        slot.Apply(marker => RpTimerWait.Died(marker, 4));
        RpWaitChange noted = ReleaseTurn(slot.Current, deathCount: 4);
        Assert.That(slot.TrySwap(noted.Before, noted.Next), Is.True);

        RpWaitDecision again = Turn(slot.Current, Look(RpWaitCase.Frontier), deathCount: 4);
        AssertStarted(again, slot.Current, Waiting(RpWaitCase.Frontier) with { DeathCount = 4, Started = Now }, false);
    }

    // 2.4, 3.1-3.4: trips are measured from the spot of the wait: for a Released bot its battleground slot (hook 1) or
    // its release point, a bind (hook 2), wherever it stands; for a waiting bot its stored spot (its slot, its bind, or
    // its warband slot, after a Convert too), whatever the hook sees now. A Left marker gives its stored spot.
    [Test]
    public void TheSpotIsTheSlotTheBindOrTheStoredSpot()
    {
        Assert.That(RpTimerWait.WaitSpot(ReleasedForTheBattleground(),
            Look(RpWaitCase.Battleground, position: AlbionArrival)), Is.EqualTo(AlbionArrivalSlot));
        Assert.That(RpTimerWait.WaitSpot(Released(),
            Look(RpWaitCase.Frontier, position: new Vector3(Bind.X + 300, Bind.Y, Bind.Z))), Is.EqualTo(Bind));
        Assert.That(RpTimerWait.WaitSpot(Released(), Look(RpWaitCase.Siege)), Is.EqualTo(Bind));

        var elsewhere = new Vector3(20_000, 20_000, 3_000);
        foreach (RpWaitCase waitCase in new[]
            { RpWaitCase.Frontier, RpWaitCase.Siege, RpWaitCase.Warband, RpWaitCase.Battleground })
        {
            RpWaitMarker waiting = Waiting(waitCase);
            Assert.That(RpTimerWait.WaitSpot(waiting, Look(RpWaitCase.Battleground, position: elsewhere)),
                Is.EqualTo(waiting.Spot));
            Assert.That(RpTimerWait.WaitSpot(waiting, Look(RpWaitCase.Siege, position: elsewhere)),
                Is.EqualTo(waiting.Spot));
        }

        RpWaitMarker converted =
            Waiting(RpWaitCase.Warband) with { Case = RpWaitCase.Siege, EventKeepId = "rvr-keep-50" };
        Assert.That(RpTimerWait.WaitSpot(converted, Look(RpWaitCase.Siege)), Is.EqualTo(BorderKeepSlot));
        RpWaitMarker left = Waiting(RpWaitCase.Warband) with { Phase = RpWaitPhase.Left };
        Assert.That(RpTimerWait.WaitSpot(left, Look(RpWaitCase.Siege)), Is.EqualTo(BorderKeepSlot));
    }
}
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/Tests/UnitTests/UT_RpTimerWait.cs (1 block(s))`.

- [ ] **Step 2: Run them and watch them fail.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWait."`
Expected: the build fails (exit code 1) and no test runs. 8 errors, every one in the new tests and every one
`CS0117`, a member missing from the class `RpTimerWait`: 1 naming `Decide` (in `Turn`) and 7 `WaitSpot` (all in
`TheSpotIsTheSlotTheBindOrTheStoredSpot`), each with the file's absolute path and the project at the end of the line:

```
source/server/Tests/UnitTests/UT_RpTimerWait.cs(696,21): error CS0117: 'RpTimerWait' does not contain a definition for 'Decide'
source/server/Tests/UnitTests/UT_RpTimerWait.cs(1260,33): error CS0117: 'RpTimerWait' does not contain a definition for 'WaitSpot'
source/server/Tests/UnitTests/UT_RpTimerWait.cs(1262,33): error CS0117: 'RpTimerWait' does not contain a definition for 'WaitSpot'
source/server/Tests/UnitTests/UT_RpTimerWait.cs(1264,33): error CS0117: 'RpTimerWait' does not contain a definition for 'WaitSpot'
source/server/Tests/UnitTests/UT_RpTimerWait.cs(1271,37): error CS0117: 'RpTimerWait' does not contain a definition for 'WaitSpot'
source/server/Tests/UnitTests/UT_RpTimerWait.cs(1273,37): error CS0117: 'RpTimerWait' does not contain a definition for 'WaitSpot'
source/server/Tests/UnitTests/UT_RpTimerWait.cs(1279,33): error CS0117: 'RpTimerWait' does not contain a definition for 'WaitSpot'
source/server/Tests/UnitTests/UT_RpTimerWait.cs(1281,33): error CS0117: 'RpTimerWait' does not contain a definition for 'WaitSpot'
```

- [ ] **Step 3: Implement.** Add the members after `JoinedGroup`, before the class's closing brace, with exactly the
code below. `WaitSpot` gives a Released marker's spot from what the hook sees (a battleground slot, else the release
point) and any other marker's stored spot. Three private builders make `Decide`'s Ignore (the marker read, kept: the
same reference, so the controller swaps nothing), Skip (the marker read latched Left, with the hook's case stored)
and Leave (latched Left); none walks. `Decide` follows the rule comment above it, in order:
another death's marker, none or a Left one is ignored (the latch); a first look ignores a warband outside battle (the
gate's), skips with no line when the bot is worth already, then for a relic, another region than the release point
(frontier and siege only), no target, a target in another region, outside its gate (2,500 from the arrival point in a
battleground, else 750 from the release point) and time left within the trip, and otherwise starts a wait at
`WaitSpot`, walking there when more than 48 from it. A wait's later turns end it for a new assignment, another keep
(a siege seen as a siege, before the region), another region and a relic; a warband marker is the gate's while the
hook sees a warband, ends as changed when it sees the frontier or a battleground, and seen as a siege must stand
within 200 of its slot (moved-away); every other wait ends as changed when the case differs. Then, for both, no target
or a target in another region ends it, then time left within the trip (due); what is left converts a warband wait into
a siege wait at its slot (the event keep stored, `Started` now, no walk) or holds, walking back past 200:

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs <<'EDIT'
<<<<<<< OLD
            _ => RpWaitChange.Keep(marker),
        };
    }
}
=======
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
}
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs (1 block(s))`.

- [ ] **Step 4: Run them and watch them pass.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWait."`
Expected: `Passed!  - Failed:     0, Passed:   114, Skipped:     0, Total:   114` (exit code 0; no warning names
`RpTimerWait.cs` or `UT_RpTimerWait.cs`). 114 = Tasks 1-3's 62 + this task's 52: 18 `[Test]` methods and 34
`[TestCase]` rows (`OutsideTheFirstLookGateSkips` 6, `TheFirstLookStartsAWait` 5,
`TheFirstLookWalksToABattlegroundSlotOnly160Away` 4, `AWaitHoldsUntilTimeLeftEqualsTheTrip` 3,
`AWaitFarFromItsSpotHoldsAndWalksBack` 3, `AnotherAssignmentOrRegionEndsAWait` 4, `ACaseChangeEndsAWait` 5,
`AGoneTargetEndsAWait` 4).

Run: `git diff --stat`
Expected: only the two files, `RpTimerWait.cs` with 138 lines added and `UT_RpTimerWait.cs` with 629, then
`2 files changed, 767 insertions(+)`.

- [ ] **Step 5: Commit.**

```bash
git add source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs source/server/Tests/UnitTests/UT_RpTimerWait.cs
git commit -F - <<'EOF'
feat(rp-wait): the first look and the wait for hooks 1 and 2

One decision per turn from the marker, what the hook sees, the time left and the trip: a first look starts a wait
at the battleground slot or the release point, walking there when more than 48 away, or skips it with a reason; a
wait holds, walking back past 200, until its time left is no more than its trip; a change of assignment, region,
case, keep or target ends it, and a held warband drafted into a battle becomes a siege wait at its slot. A Left
marker is never stopped again for that death.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

Expected: `2 files changed, 767 insertions(+)`.

---

### Task 5: The warband gate

**Files:**
- Modify: `source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs` (add `WarbandWaits` and `WarbandMarks`, with two
  private helpers, at the end of the class `RpTimerWait`)
- Modify: `source/server/Tests/UnitTests/UT_RpTimerWait.cs` (22 tests at the class's end, with the values and helpers
  they share)
- Test: `source/server/Tests/UnitTests/UT_RpTimerWait.cs`

**Spec:** 3.4 (the warband gate: who holds it, the march, the markers while it holds and when it opens), section 5
(relics), section 6 (off: go, no writes), 7.1, 7.2 (the gate's writes), 10.1 ("Warband gate" and Died's "the gate
ignores it").

**Interfaces:**
- Consumes: Task 1's types (`RpWaitMarker`, `RpWaitPhase`, `RpWaitCase`, `RpWaitAction`, `RpWaitReason`,
  `RpWaitChange` with `Keep` and `Changes`, `RpDeathRecord`, `RpWarbandMember`, `RpWarbandGate`, `RpWaitSlot` with
  `Current`, `TrySwap` and `Apply`); Task 2's `RpTimerWait.TripMilliseconds` and `RpTimerWait.Distance2D`; Task 3's
  private `Latch(RpWaitMarker marker, RpWaitAction action, RpWaitReason reason)` (each latch of the gate) and, in the
  tests only, `Note`, `Died` and `JoinedGroup`; `eAutonomousObjectiveKind` (`DOL.GS`). The new members go after
  `Decide`, the class's last. In the tests: Task 1's `Bind`, `Released()` and `SlotWith(...)`; Task 2's `DeathTick`;
  Task 3's `RvrAssignment`, `BorderKeepSlot`, `WarbandSession`, `Waiting(RpWaitCase)`, `PreviousDeathsMarker()`,
  `ReleaseTurn(...)`, `LaterTurn(...)`, `AssertLatched` and `AssertKept`; Task 4's `Now`, `CamelotRegion` and
  `Camelot`.
- Produces, in `public static class RpTimerWait`:
  - `public static RpWarbandGate WarbandWaits(bool enabled, eAutonomousObjectiveKind kind, bool forceCommitted,
    bool relicCarrier, ushort rendezvousRegion, Vector3 rendezvous, IReadOnlyList<RpWarbandMember> members)` (Task 9's
    `RpTimerWaitScript.WarbandWaits(...)` asks it under the coordinator lock, for hook 4)
  - `public static RpWaitChange[] WarbandMarks(RpWarbandGate gate, ushort rendezvousRegion,
    IReadOnlyList<RpWarbandMember> members, string sessionId, long now)` (Task 9 swaps each change against the marker
    it read and logs a line only after a successful swap)
  - `private static bool ReleasedForItsDeath(RpWarbandMember member)` (a member whose marker is Released or Waiting for
    its own death count: the only members that hold the gate and the only markers it writes) and `private static
    RpWaitChange WarbandMark(RpWarbandGate gate, ushort rendezvousRegion, RpWarbandMember member, string sessionId,
    long now)` (one member's change)

- [ ] **Step 1: Write the failing tests.** Add them at the end of the class in `UT_RpTimerWait.cs`, after Task 4's
last test, with the values and helpers they share: the warband's rendezvous by the Albion border keep, two more
members' slots, and a death 9,550 from the rendezvous (a march of 50,000 ms at 191 units/s); the gate's two values that
go with no march (it opens on the members, or it writes nothing); a member released to Camelot; a member as the gate
sees it (`Member`, each input overridable, its death record with a `with`); the gate and its writes on one pass
(`Gate` and `Marks`, through which every test calls `WarbandWaits` and `WarbandMarks`); and two checks (a member
turned Waiting, nothing written). `TheGateWaitsWhileTheMostTimeLeftExceedsTheMarch` takes four rows, two that hold and
two that go:

```bash
python3 /tmp/hdc-edit.py source/server/Tests/UnitTests/UT_RpTimerWait.cs <<'EDIT'
<<<<<<< OLD
        Assert.That(RpTimerWait.WaitSpot(left, Look(RpWaitCase.Siege)), Is.EqualTo(BorderKeepSlot));
    }
}
=======
        Assert.That(RpTimerWait.WaitSpot(left, Look(RpWaitCase.Siege)), Is.EqualTo(BorderKeepSlot));
    }

    // The warband of 3.4, regrouping by the Albion border keep in the Albion frontier (region 1): its rendezvous (the
    // session's Rendezvous), two more members' slots beside BorderKeepSlot, and where a member died this death, 9,550
    // from the rendezvous: a march of 50,000 ms at 191 units/s (300 lower: the march is horizontal).
    private static readonly Vector3 Rendezvous = new(29_500, 31_000, 4_310);
    private static readonly Vector3 SecondSlot = new(29_360, 31_220, 4_310);
    private static readonly Vector3 ThirdSlot = new(29_500, 30_740, 4_310);
    private static readonly Vector3 DeathSpot = new(29_500, 40_550, 4_010);
    private const long March = 50_000;

    // The gate's go with no march: it opens on the members (it writes), or it writes nothing (the switch off, a
    // session that is not RvR, a committed force).
    private static readonly RpWarbandGate OpensWithNoMarch = new(false, true, 0, 0);
    private static readonly RpWarbandGate GoesWithNoWrites = new(false, false, 0, 0);

    // A warband member released for death 3 to Albion's capital, Camelot (an invader's or a far death's release),
    // with its RvR assignment.
    private static RpWaitMarker ReleasedInCamelot() =>
        new(3, RpWaitPhase.Released, RpWaitCase.None, CamelotRegion, Camelot, CamelotRegion, Camelot, RvrAssignment,
            null, null, 0);

    // A member as the gate sees it on a pass (3.4): its marker and time left, its death count 3 and its death record
    // for it at DeathSpot in the Albion frontier, standing in the Albion frontier at its slot (BorderKeepSlot) with
    // its RvR assignment and a best speed of 191. Each test sets what it is about (the record with a with).
    private static RpWarbandMember Member(RpWaitMarker marker, long timeLeft, int deathCount = 3, ushort region = 1,
        Vector3? slot = null, string assignmentId = RvrAssignment, double bestSpeed = 191) =>
        new(marker, deathCount, timeLeft, new RpDeathRecord(deathCount, 1, DeathSpot, DeathTick, DeathTick), region,
            slot ?? BorderKeepSlot, assignmentId, bestSpeed);

    // Hook 4's gate on a pass of that warband's regroup: the switch on, an RvR session, no committed force and no
    // relic carrier, unless a test says otherwise.
    private static RpWarbandGate Gate(RpWarbandMember[] members, bool enabled = true,
        eAutonomousObjectiveKind kind = eAutonomousObjectiveKind.RvR, bool forceCommitted = false,
        bool relicCarrier = false) =>
        RpTimerWait.WarbandWaits(enabled, kind, forceCommitted, relicCarrier, 1, Rendezvous, members);

    // The gate's writes on that pass, at Now, for the warband's session.
    private static RpWaitChange[] Marks(RpWarbandGate gate, RpWarbandMember[] members) =>
        RpTimerWait.WarbandMarks(gate, 1, members, WarbandSession, Now);

    // The holding gate turns the member's Released marker Waiting (a new marker): case warband, the rendezvous region,
    // its slot as the spot, its assignment id now, the session id, no event keep, Started now; its start line.
    private static void AssertTurnedWaiting(RpWaitChange change, RpWarbandMember member)
    {
        Assert.That(change.Before, Is.SameAs(member.Marker));
        Assert.That(change.Changes, Is.True);
        Assert.That(change.Next, Is.EqualTo(member.Marker with
        {
            Phase = RpWaitPhase.Waiting,
            Case = RpWaitCase.Warband,
            Region = 1,
            Spot = member.Slot,
            AssignmentId = member.AssignmentId,
            SessionId = WarbandSession,
            EventKeepId = null,
            Started = Now,
        }));
        Assert.That(change.Action, Is.EqualTo(RpWaitAction.Start));
        Assert.That(change.Reason, Is.EqualTo(RpWaitReason.None));
    }

    // The gate writes nothing: one change per member, in member order, each keeping its marker (null included).
    private static void AssertNothingWritten(RpWaitChange[] changes, RpWarbandMember[] members)
    {
        Assert.That(changes, Has.Length.EqualTo(members.Length));
        for (int i = 0; i < members.Length; i++)
            AssertKept(changes[i], members[i].Marker);
    }

    // 3.4: the warband leaves together once its member released for this death with the most time left can make the
    // march from the rendezvous to where it died: the gate holds while that time left is more than the march, and an
    // equal one goes. The holder is the member with the most time left wherever it stands in the party, and the march
    // is to its own death, not another member's (19,100 away: 100,000 ms).
    [TestCase(240_000L, true)]
    [TestCase(50_001L, true)]
    [TestCase(50_000L, false)]
    [TestCase(49_999L, false)]
    public void TheGateWaitsWhileTheMostTimeLeftExceedsTheMarch(long holderTimeLeft, bool waits)
    {
        var farDeath = new RpDeathRecord(3, 1, new Vector3(Rendezvous.X, Rendezvous.Y + 19_100, 4_000), DeathTick,
            DeathTick);
        RpWarbandMember[] members =
        {
            Member(Released(), 30_000, slot: SecondSlot) with { Death = farDeath },
            Member(Released(), holderTimeLeft),
        };

        Assert.That(Gate(members), Is.EqualTo(new RpWarbandGate(waits, true, March, holderTimeLeft)));
    }

    // 3.4, choice 18: a member resurrected in the field has no marker for its current death (none, or its previous
    // death's, latched Left), so it doesn't hold the gate, however much time it has left; a released member does.
    [Test]
    public void AResurrectedMemberDoesNotHoldTheGate()
    {
        RpWarbandMember resurrected = Member(PreviousDeathsMarker(), 280_000);
        RpWarbandMember neverReleased = Member(null, 290_000, slot: SecondSlot);
        RpWarbandMember released = Member(Released(), 40_000, slot: ThirdSlot);

        Assert.That(Gate(new[] { resurrected, neverReleased, released }),
            Is.EqualTo(new RpWarbandGate(false, true, March, 40_000)));
        Assert.That(Gate(new[] { resurrected, neverReleased }), Is.EqualTo(OpensWithNoMarch));
    }

    // Section 5, 3.4: never with a relic carrier in the party: go, even with members' time left above the march, and
    // the gate opens on them as on any opening.
    [Test]
    public void ARelicCarrierMeansGo()
    {
        RpWarbandMember[] members =
        {
            Member(Waiting(RpWaitCase.Warband), 200_000),
            Member(Released(), 240_000, slot: SecondSlot),
        };

        RpWarbandGate gate = Gate(members, relicCarrier: true);

        Assert.That(gate, Is.EqualTo(OpensWithNoMarch));
        RpWaitChange[] changes = Marks(gate, members);
        AssertLatched(changes[0], members[0].Marker, RpWaitAction.Leave, RpWaitReason.Due);
        AssertLatched(changes[1], members[1].Marker, RpWaitAction.Skip, RpWaitReason.Trip);
    }

    // 3.4: only RvR sessions wait. A Group PvE party reaches the same regroup completion after a wipe, and a monster
    // kill restarts the timer too: go, and nothing written, even with members' time left above the march. Any other
    // kind but RvR likewise.
    [Test]
    public void AGroupPveSessionMeansGoAndWritesNothing()
    {
        RpWarbandMember[] members =
        {
            Member(Waiting(RpWaitCase.Warband), 200_000),
            Member(Released(), 240_000, slot: SecondSlot),
        };
        var notRvr = new[]
        {
            eAutonomousObjectiveKind.GroupPve, eAutonomousObjectiveKind.SoloPve, eAutonomousObjectiveKind.Battleground,
        };
        foreach (eAutonomousObjectiveKind kind in notRvr)
        {
            RpWarbandGate gate = Gate(members, kind: kind);

            Assert.That(gate, Is.EqualTo(GoesWithNoWrites), kind.ToString());
            AssertNothingWritten(Marks(gate, members), members);
        }
    }

    // 3.4: every member released for this death is worth points already (time left 0): nobody holds the gate, and its
    // opening latches them, a Released one with no line, a Waiting one with its leave.
    [Test]
    public void AllWorthMeansGo()
    {
        RpWarbandMember[] members =
        {
            Member(Waiting(RpWaitCase.Warband), 0),
            Member(Released(), 0, slot: SecondSlot),
        };

        RpWarbandGate gate = Gate(members);

        Assert.That(gate, Is.EqualTo(OpensWithNoMarch));
        RpWaitChange[] changes = Marks(gate, members);
        AssertLatched(changes[0], members[0].Marker, RpWaitAction.Leave, RpWaitReason.Due);
        AssertLatched(changes[1], members[1].Marker, RpWaitAction.None, RpWaitReason.None);
    }

    // Section 6: with the switch off the gate says go at once and writes nothing, even with members Waiting or Released
    // for this death above the march: a Waiting member stays Waiting until its own hook 3 ends it (off), never the gate
    // (due), and a Released one stays Released, as hook 3 leaves it.
    [Test]
    public void TheSwitchOffMeansGoAndWritesNothing()
    {
        RpWarbandMember[] members =
        {
            Member(Waiting(RpWaitCase.Warband), 200_000),
            Member(Released(), 240_000, slot: SecondSlot),
        };

        RpWarbandGate gate = Gate(members, enabled: false);

        Assert.That(gate, Is.EqualTo(GoesWithNoWrites));
        AssertNothingWritten(Marks(gate, members), members);
        AssertLatched(LaterTurn(members[0].Marker, enabled: false), members[0].Marker, RpWaitAction.Leave,
            RpWaitReason.Off);
        AssertKept(LaterTurn(members[1].Marker, enabled: false), members[1].Marker);
    }

    // 3.4 "Not in a muster": a warband enrolled in an event whose battle has not started still regroups, but its force
    // is committed (IsForceCommitted): go, and nothing written, even with members' time left above the march. A member
    // already Waiting is its hook 3's to end (called, at the muster order).
    [Test]
    public void ACommittedForceMeansGoAndWritesNothing()
    {
        RpWarbandMember[] members =
        {
            Member(Waiting(RpWaitCase.Warband), 200_000),
            Member(Released(), 240_000, slot: SecondSlot),
        };

        RpWarbandGate gate = Gate(members, forceCommitted: true);

        Assert.That(gate, Is.EqualTo(GoesWithNoWrites));
        AssertNothingWritten(Marks(gate, members), members);
        AssertLatched(LaterTurn(members[0].Marker, musterOrder: true), members[0].Marker, RpWaitAction.Leave,
            RpWaitReason.Called);
    }

    // 3.4: the march needs where the holder died for this death, in the rendezvous region. No death record, one for
    // its previous death, or a death in another region (an invader's, in the Midgard frontier): go, even though
    // another member's record would give a march (the holder decides).
    [Test]
    public void NoMatchingDeathRecordOrADeathInAnotherRegionMeansGo()
    {
        RpWarbandMember other = Member(Released(), 100_000, slot: SecondSlot);
        RpWarbandMember holder = Member(Released(), 240_000);
        Assert.That(Gate(new[] { other, holder }), Is.EqualTo(new RpWarbandGate(true, true, March, 240_000)));

        RpDeathRecord[] unusable =
        {
            null,
            new RpDeathRecord(2, 1, DeathSpot, DeathTick - 400_000, DeathTick - 400_000),
            new RpDeathRecord(3, 100, DeathSpot, DeathTick, DeathTick),
        };
        foreach (RpDeathRecord death in unusable)
            Assert.That(Gate(new[] { other, holder with { Death = death } }), Is.EqualTo(OpensWithNoMarch));
    }

    // 3.4: the march is at the best speed of the fastest member, holding the gate or not: a singer's own
    // song of 140 (267.4 units/s) makes the 9,550 a march of 35,714 ms, so 40,000 left holds; a resurrected member at
    // 300 (another's song on it) makes it 31,833.
    [Test]
    public void TheMarchIsAtTheFastestMembersBestSpeed()
    {
        RpWarbandMember holder = Member(Released(), 40_000);
        Assert.That(Gate(new[] { holder }), Is.EqualTo(new RpWarbandGate(false, true, March, 40_000)));

        RpWarbandMember singer = Member(Released(), 20_000, slot: SecondSlot, bestSpeed: 267.4);
        Assert.That(Gate(new[] { holder, singer }), Is.EqualTo(new RpWarbandGate(true, true, 35_714, 40_000)));

        RpWarbandMember resurrected = Member(null, 250_000, slot: ThirdSlot, bestSpeed: 300);
        Assert.That(Gate(new[] { holder, singer, resurrected }),
            Is.EqualTo(new RpWarbandGate(true, true, 31_833, 40_000)));
    }

    // 3.4, 2.4: a member whose wait for death 3 the gate ended is killed again, 5,730 from the rendezvous (a march of
    // 30,000 ms), and released: hook 3 writes Released for death 4 over its Left marker, which holds the gate again
    // and turns Waiting at its slot.
    [Test]
    public void AMemberKilledAgainAndReleasedMakesItWaitAgain()
    {
        RpWaitSlot slot = SlotWith(Waiting(RpWaitCase.Warband));
        RpWarbandMember[] members = { Member(slot.Current, March) };
        RpWarbandGate opened = Gate(members);
        Assert.That(opened.Waits, Is.False);
        RpWaitChange due = Marks(opened, members)[0];
        Assert.That(due.Reason, Is.EqualTo(RpWaitReason.Due));
        Assert.That(slot.TrySwap(due.Before, due.Next), Is.True);

        Assert.That(slot.Apply(marker => RpTimerWait.Died(marker, 4)).Changes, Is.False);
        RpWaitChange noted = ReleaseTurn(slot.Current, deathCount: 4);
        Assert.That(slot.TrySwap(noted.Before, noted.Next), Is.True);

        var secondDeath = new RpDeathRecord(4, 1, new Vector3(Rendezvous.X + 5_730, Rendezvous.Y, 4_200),
            DeathTick + 400_000, DeathTick + 400_000);
        members = new[] { Member(slot.Current, 280_000, deathCount: 4) with { Death = secondDeath } };
        RpWarbandGate holding = Gate(members);

        Assert.That(holding, Is.EqualTo(new RpWarbandGate(true, true, 30_000, 280_000)));
        RpWaitChange[] changes = Marks(holding, members);
        AssertTurnedWaiting(changes[0], members[0]);
        Assert.That(changes[0].Next.DeathCount, Is.EqualTo(4));
        Assert.That(slot.TrySwap(changes[0].Before, changes[0].Next), Is.True);
    }

    // 3.4: while the gate holds, each member Released for this death in the rendezvous region turns Waiting at the
    // swap that writes it, with one start line: case warband, its slot as the spot, its assignment id now (a newer
    // one than at its release, so its hook 3 keeps the wait), the session id, Started now. The holder too.
    [Test]
    public void WhileHoldingReleasedMembersAtTheRendezvousTurnWaiting()
    {
        RpWarbandMember[] members =
        {
            Member(Released(), 240_000),
            Member(Released(), 120_000, slot: SecondSlot, assignmentId: "albion-40-13-RvR"),
        };
        RpWarbandGate gate = Gate(members);
        Assert.That(gate, Is.EqualTo(new RpWarbandGate(true, true, March, 240_000)));

        RpWaitChange[] changes = Marks(gate, members);

        Assert.That(changes, Has.Length.EqualTo(2));
        AssertTurnedWaiting(changes[0], members[0]);
        AssertTurnedWaiting(changes[1], members[1]);
        Assert.That(changes[0].Next.Spot, Is.EqualTo(BorderKeepSlot));
        Assert.That(changes[1].Next.Spot, Is.EqualTo(SecondSlot));
        Assert.That(changes[1].Next.AssignmentId, Is.EqualTo("albion-40-13-RvR"));
        Assert.That(changes[1].Next.SessionId, Is.EqualTo("albion-7f3a-007"));
        Assert.That(changes[1].Next.ReleasePoint, Is.EqualTo(Bind));
        AssertKept(LaterTurn(changes[1].Next, assignmentId: "albion-40-13-RvR"), changes[1].Next);
    }

    // 3.4, a ruling (the spec's gate has no time-left condition): while the gate holds, a member Released for this
    // death in the rendezvous region but worth points already (time left 0) stays Released, as a first look skips a
    // bot already worth points with no line: no wait starts and no start line is logged. The gate's opening latches
    // it with no line.
    [Test]
    public void WhileHoldingAReleasedMemberAlreadyWorthStaysReleased()
    {
        RpWarbandMember[] members =
        {
            Member(Released(), 240_000),
            Member(Released(), 0, slot: SecondSlot),
        };
        RpWarbandGate gate = Gate(members);
        Assert.That(gate, Is.EqualTo(new RpWarbandGate(true, true, March, 240_000)));

        RpWaitChange[] changes = Marks(gate, members);

        Assert.That(changes, Has.Length.EqualTo(2));
        AssertTurnedWaiting(changes[0], members[0]);
        AssertKept(changes[1], members[1].Marker);

        RpWarbandMember[] opening = { members[0] with { TimeLeft = March }, members[1] };
        gate = Gate(opening);
        Assert.That(gate.Waits, Is.False);
        AssertLatched(Marks(gate, opening)[1], members[1].Marker, RpWaitAction.None, RpWaitReason.None);
    }

    // 3.4: a member already Waiting is not written again while the gate holds: on later passes (once a second) its
    // marker stays the same reference and no second start is logged, and it still holds the gate.
    [Test]
    public void AWaitingMemberIsNotWrittenAgain()
    {
        RpWaitSlot slot = SlotWith(Released());
        RpWarbandMember[] first = { Member(slot.Current, 240_000) };
        RpWaitChange start = Marks(Gate(first), first)[0];
        Assert.That(start.Action, Is.EqualTo(RpWaitAction.Start));
        Assert.That(slot.TrySwap(start.Before, start.Next), Is.True);

        foreach (long timeLeft in new[] { 239_000L, 238_000L })
        {
            RpWarbandMember[] later = { Member(slot.Current, timeLeft) };
            RpWarbandGate gate = Gate(later);

            Assert.That(gate, Is.EqualTo(new RpWarbandGate(true, true, March, timeLeft)));
            AssertNothingWritten(Marks(gate, later), later);
        }
    }

    // 3.4: a member released to its capital stays Released while it is there and still holds the gate (its death in
    // the frontier sets the march); on the first pass after it enters the rendezvous region it turns Waiting at its
    // slot, the region of its wait the rendezvous region.
    [Test]
    public void AMemberInAnotherRegionStaysReleasedThenTurnsWaitingWhenItArrives()
    {
        RpWarbandMember atSlot = Member(Waiting(RpWaitCase.Warband), 150_000);
        RpWarbandMember away = Member(ReleasedInCamelot(), 280_000, region: CamelotRegion, slot: SecondSlot);
        RpWarbandMember[] members = { atSlot, away };
        RpWarbandGate gate = Gate(members);

        Assert.That(gate, Is.EqualTo(new RpWarbandGate(true, true, March, 280_000)));
        AssertNothingWritten(Marks(gate, members), members);

        RpWarbandMember arrived = away with { Region = 1, TimeLeft = 220_000 };
        members = new[] { atSlot with { TimeLeft = 90_000 }, arrived };
        gate = Gate(members);

        Assert.That(gate, Is.EqualTo(new RpWarbandGate(true, true, March, 220_000)));
        RpWaitChange[] changes = Marks(gate, members);
        AssertKept(changes[0], atSlot.Marker);
        AssertTurnedWaiting(changes[1], arrived);
        Assert.That(changes[1].Next.Region, Is.EqualTo(1));
        Assert.That(changes[1].Next.ReleaseRegion, Is.EqualTo(CamelotRegion));
    }

    // 3.4: while the gate holds, a member resurrected in the field (no marker for its death: none, or its previous
    // death's) gets none, and a member whose marker is Left for this death (its first look skipped, or its hook 3
    // ended its wait) stays Left: it walks back with the regroup and fights on.
    [Test]
    public void AResurrectedOrLeftMemberGetsNoMarker()
    {
        RpWarbandMember[] members =
        {
            Member(Released(), 240_000),
            Member(null, 250_000, slot: SecondSlot),
            Member(PreviousDeathsMarker(), 250_000, slot: SecondSlot),
            Member(Released() with { Phase = RpWaitPhase.Left, Case = RpWaitCase.Frontier }, 200_000, slot: ThirdSlot),
            Member(Waiting(RpWaitCase.Warband) with { Phase = RpWaitPhase.Left }, 200_000),
        };
        RpWarbandGate gate = Gate(members);

        Assert.That(gate, Is.EqualTo(new RpWarbandGate(true, true, March, 240_000)));
        RpWaitChange[] changes = Marks(gate, members);
        AssertTurnedWaiting(changes[0], members[0]);
        for (int i = 1; i < members.Length; i++)
            AssertKept(changes[i], members[i].Marker);
    }

    // 3.4: when the gate opens, every member's marker for its current death is latched Left: a Waiting one with its
    // leave (due), a Released one still worth nothing with its skip (trip), wherever it stands, and a Released one
    // worth points already with no line. An older death's marker (Left, 3.7) and no marker are not touched.
    [Test]
    public void OpeningLatchesEveryMemberForThisDeath()
    {
        RpWarbandMember[] members =
        {
            Member(Waiting(RpWaitCase.Warband), March),
            Member(Released(), 30_000, slot: SecondSlot),
            Member(ReleasedInCamelot(), 20_000, region: CamelotRegion, slot: ThirdSlot),
            Member(Released(), 0, slot: ThirdSlot),
            Member(PreviousDeathsMarker(), 250_000),
            Member(null, 250_000),
        };
        RpWarbandGate gate = Gate(members);

        Assert.That(gate, Is.EqualTo(new RpWarbandGate(false, true, March, March)));
        RpWaitChange[] changes = Marks(gate, members);
        Assert.That(changes, Has.Length.EqualTo(6));
        AssertLatched(changes[0], members[0].Marker, RpWaitAction.Leave, RpWaitReason.Due);
        AssertLatched(changes[1], members[1].Marker, RpWaitAction.Skip, RpWaitReason.Trip);
        AssertLatched(changes[2], members[2].Marker, RpWaitAction.Skip, RpWaitReason.Trip);
        AssertLatched(changes[3], members[3].Marker, RpWaitAction.None, RpWaitReason.None);
        AssertKept(changes[4], members[4].Marker);
        AssertKept(changes[5], null);
    }

    // 3.4, 3.5: a member whose wait its hook 3 has already ended (its force's muster order: called) gets no new wait
    // while the gate holds and no second leave (due) when it opens.
    [Test]
    public void AMarkerHook3AlreadyEndedGetsNoSecondLeave()
    {
        RpWaitSlot slot = SlotWith(Waiting(RpWaitCase.Warband));
        RpWaitChange called = LaterTurn(slot.Current, musterOrder: true);
        Assert.That(called.Reason, Is.EqualTo(RpWaitReason.Called));
        Assert.That(slot.TrySwap(called.Before, called.Next), Is.True);
        RpWarbandMember ended = Member(slot.Current, 200_000);

        RpWarbandMember[] holding = { ended, Member(Released(), 240_000, slot: SecondSlot) };
        RpWarbandGate gate = Gate(holding);
        Assert.That(gate.Waits, Is.True);
        AssertKept(Marks(gate, holding)[0], slot.Current);

        RpWarbandMember[] opening = { ended with { TimeLeft = 40_000 }, Member(Released(), 30_000, slot: SecondSlot) };
        gate = Gate(opening);
        Assert.That(gate.Waits, Is.False);
        AssertKept(Marks(gate, opening)[0], slot.Current);
    }

    // 7.2: the gate decides from the markers it read and swaps each change against its read. A marker that turns Left
    // on another thread in between (a player's invite while Released; its own hook 3 while Waiting, here out of its
    // group) stays Left: the gate's swap fails, and it logs nothing.
    [Test]
    public void AMarkerThatTurnsLeftBetweenReadAndWriteStaysLeft()
    {
        RpWaitSlot released = SlotWith(Released());
        RpWarbandMember[] holding = { Member(released.Current, 240_000) };
        RpWaitChange start = Marks(Gate(holding), holding)[0];
        Assert.That(start.Action, Is.EqualTo(RpWaitAction.Start));
        RpWaitChange invited = released.Apply(marker => RpTimerWait.JoinedGroup(marker, 3, true));
        Assert.That(released.TrySwap(start.Before, start.Next), Is.False);
        Assert.That(released.Current, Is.SameAs(invited.Next));
        Assert.That(released.Current.Phase, Is.EqualTo(RpWaitPhase.Left));

        RpWaitSlot waiting = SlotWith(Waiting(RpWaitCase.Warband));
        RpWarbandMember[] opening = { Member(waiting.Current, March) };
        RpWaitChange due = Marks(Gate(opening), opening)[0];
        Assert.That(due.Reason, Is.EqualTo(RpWaitReason.Due));
        RpWaitChange changed = LaterTurn(waiting.Current, inGroup: false);
        Assert.That(waiting.TrySwap(changed.Before, changed.Next), Is.True);
        Assert.That(waiting.TrySwap(due.Before, due.Next), Is.False);
        Assert.That(waiting.Current, Is.SameAs(changed.Next));
        Assert.That(waiting.Current.Phase, Is.EqualTo(RpWaitPhase.Left));
    }

    // 3.7: a member killed while waiting has its death count raised before the Dying handler latches its marker Left
    // (died). Before the handler and after it, the gate neither holds for that marker nor writes it, holding or
    // opening: no second leave.
    [Test]
    public void TheGateIgnoresAMarkerLatchedByADeath()
    {
        RpWaitSlot slot = SlotWith(Waiting(RpWaitCase.Warband));
        RpWarbandMember released = Member(Released(), 30_000, slot: SecondSlot);
        RpWarbandMember killed = Member(slot.Current, 300_000, deathCount: 4);

        RpWarbandMember[] members = { killed, released };
        RpWarbandGate gate = Gate(members);
        Assert.That(gate, Is.EqualTo(new RpWarbandGate(false, true, March, 30_000)));
        AssertKept(Marks(gate, members)[0], killed.Marker);

        RpWaitChange died = slot.Apply(marker => RpTimerWait.Died(marker, 4));
        Assert.That(died.Reason, Is.EqualTo(RpWaitReason.Died));
        RpWarbandMember latched = killed with { Marker = slot.Current };
        members = new[] { latched, released };
        gate = Gate(members);
        Assert.That(gate, Is.EqualTo(new RpWarbandGate(false, true, March, 30_000)));
        AssertKept(Marks(gate, members)[0], slot.Current);

        members = new[] { latched, released with { TimeLeft = 240_000 } };
        gate = Gate(members);
        Assert.That(gate, Is.EqualTo(new RpWarbandGate(true, true, March, 240_000)));
        AssertKept(Marks(gate, members)[0], slot.Current);
    }
}
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/Tests/UnitTests/UT_RpTimerWait.cs (1 block(s))`.

- [ ] **Step 2: Run them and watch them fail.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWait."`
Expected: the build fails (exit code 1) and no test runs. 2 errors, both in the new helpers and both `CS0117`, a
member missing from the class `RpTimerWait`: `WarbandWaits` (in `Gate`) and `WarbandMarks` (in `Marks`), each with the
file's absolute path and the project at the end of the line:

```
source/server/Tests/UnitTests/UT_RpTimerWait.cs(1317,21): error CS0117: 'RpTimerWait' does not contain a definition for 'WarbandWaits'
source/server/Tests/UnitTests/UT_RpTimerWait.cs(1321,21): error CS0117: 'RpTimerWait' does not contain a definition for 'WarbandMarks'
```

- [ ] **Step 3: Implement.** Add the members after `Decide`, before the class's closing brace, with exactly the code
below. `ReleasedForItsDeath` says whether a member's marker is Released or Waiting for its own death count: only such a
member holds the gate, and only its marker is the gate's to write. `WarbandWaits` follows the rule comment above it, in
order: the switch off, a session that is not RvR or a committed force go and write nothing; a relic carrier goes (the
gate opens); the holder is the member released for its death with the most time left above 0 (the first of equals);
none, or a holder whose death record is missing, for another death or in another region than the rendezvous, goes;
otherwise the march is the straight line from the rendezvous to the holder's death at the fastest member's best speed,
and the gate holds while the holder's time left is more than the march. `WarbandMark` makes one member's change and
`WarbandMarks` one per member, in member order: nothing unless the gate writes and the member is released for its
death; holding turns a Released marker in the rendezvous region with time left above 0 (a ruling: Global Constraints)
Waiting at the member's slot (case warband, the rendezvous region, its assignment id now, the session id, no event
keep, `Started` now); opening latches it with Task 3's `Latch`: a Waiting marker leaves (due), a Released one skips
(trip) with time left, else with no line:

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs <<'EDIT'
<<<<<<< OLD
            Distance2D(look.Position, marker.Spot) > WalkBackBeyond);
    }
}
=======
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
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs (1 block(s))`.

- [ ] **Step 4: Run them and watch them pass.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWait."`
Expected: `Passed!  - Failed:     0, Passed:   136, Skipped:     0, Total:   136` (exit code 0; no warning names
`RpTimerWait.cs` or `UT_RpTimerWait.cs`). 136 = Tasks 1-4's 114 + this task's 22: 18 `[Test]` methods and the 4
`[TestCase]` rows of `TheGateWaitsWhileTheMostTimeLeftExceedsTheMarch`.

Run: `git diff --stat`
Expected: only the two files, `RpTimerWait.cs` with 95 lines added and `UT_RpTimerWait.cs` with 502, then
`2 files changed, 597 insertions(+)`.

- [ ] **Step 5: Commit.**

```bash
git add source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs source/server/Tests/UnitTests/UT_RpTimerWait.cs
git commit -F - <<'EOF'
feat(rp-wait): the warband gate

A frontier warband leaves together once the member released for this death with the most time left can make the
march from the rendezvous to where it died, at the fastest member's best speed. While the gate holds, released
members at the rendezvous turn Waiting at their slots; when it opens, every wait for this death is latched.
Resurrected members don't hold it (owner's choice 18). With the switch off, a session that is not RvR or a committed
force, the gate says go and writes nothing.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

Expected: `2 files changed, 597 insertions(+)`.

---

### Task 6: What counts as waiting

**Files:**
- Modify: `source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs` (add `IsWaiting` at the end of the class
  `RpTimerWait`)
- Modify: `source/server/Tests/UnitTests/UT_RpTimerWait.cs` (24 tests at the class's end, with the two helpers they
  share)
- Test: `source/server/Tests/UnitTests/UT_RpTimerWait.cs`

**Spec:** 2.4 ("Counts as waiting": the marker and cheap reads of the bot, no clock; the release's first-look places),
3.1 (a released battleground bot before hook 1), 3.6 (no recruiting of waiting bots), section 4 (no charging what it
only sees, through fights), 7.1, 10.1 ("Is waiting" and Died's "`IsWaiting` ignores it").

**Interfaces:**
- Consumes: Task 1's types (`RpWaitMarker`, `RpWaitPhase`, `RpWaitCase`, and in the tests `RpWaitSlot` with
  `Current`, `TrySwap` and `Apply`, and `RpWaitChange`); Task 2's `RpTimerWait.IsBattlegroundRegion`,
  `RpTimerWait.IsFrontierRegion`, `RpTimerWait.Distance2D` and the constants `ArrivalGate` (2,500) and `BindGate`
  (750), and in the tests `WorthlessForMilliseconds` and the region constants; in the tests only, Task 3's `Note` and
  `Died`. The new member goes after `WarbandMarks`, the class's last. In the tests: Task 1's `Bind`, `Released()` and
  `SlotWith(...)`; Task 2's `DeathTick` and `RpWorthSeconds`; Task 3's `Thidranki`, `AlbionArrival`,
  `Waiting(RpWaitCase)`, `ReleaseTurn(...)` and `AssertKept`; Task 4's `Now`, `TimeLeft`, `CamelotRegion` and
  `ReleasedForTheBattleground()`; Task 5's `ReleasedInCamelot()`.
- Produces, in `public static class RpTimerWait`:
  - `public static bool IsWaiting(bool enabled, RpWaitMarker marker, int deathCount, long timeLeft, ushort region,
    Vector3 position, string assignmentId, bool playerLed, bool inGroup, Vector3? battlegroundArrival)` (Task 9's
    `RpTimerWaitScript.IsWaiting(GameBot)` asks it for hooks 5 and 6, with the bot's realm's `BotArrival` only for a
    Released marker in a battleground region)

- [ ] **Step 1: Write the failing tests.** Add them at the end of the class in `UT_RpTimerWait.cs`, after Task 5's
last test, with the two helpers they share: the four cases of wait (`EveryWaitCase`), and the question hooks 5 and 6
ask (`Counts`, through which every test but one row calls `IsWaiting`: the switch on, 240 s left, the bot at the
marker's spot in its region with its assignment id, not player-led, grouped only for a warband marker, no
battleground arrival; each input overridable). `AWaitingBotCountsWithNoClock` takes one row per case of wait;
`EachMismatchStopsItCounting` one row per mismatch (spec 10.1's seven, and no marker), each over the four cases; the
two Released tests one row per distance, at and just past their gates:

```bash
python3 /tmp/hdc-edit.py source/server/Tests/UnitTests/UT_RpTimerWait.cs <<'EDIT'
<<<<<<< OLD
        Assert.That(gate, Is.EqualTo(new RpWarbandGate(true, true, March, 240_000)));
        AssertKept(Marks(gate, members)[0], slot.Current);
    }
}
=======
        Assert.That(gate, Is.EqualTo(new RpWarbandGate(true, true, March, 240_000)));
        AssertKept(Marks(gate, members)[0], slot.Current);
    }

    // The four cases of wait, in the order of section 3.
    private static readonly RpWaitCase[] EveryWaitCase =
        { RpWaitCase.Frontier, RpWaitCase.Siege, RpWaitCase.Warband, RpWaitCase.Battleground };

    // Hooks 5 and 6 ask whether the bot counts as waiting (2.4), for death count 3: the switch on, 240 s left on its
    // timer, standing at the marker's spot in its region with its assignment id, not in a player's group, in a group
    // only for a warband marker, and no battleground arrival (the wiring gives one only for a Released marker in a
    // battleground region). Each test sets what it is about.
    private static bool Counts(RpWaitMarker marker, bool enabled = true, int deathCount = 3, long timeLeft = TimeLeft,
        ushort? region = null, Vector3? position = null, string assignmentId = null, bool playerLed = false,
        bool? inGroup = null, Vector3? battlegroundArrival = null) =>
        RpTimerWait.IsWaiting(enabled, marker, deathCount, timeLeft, region ?? marker.Region, position ?? marker.Spot,
            assignmentId ?? marker.AssignmentId, playerLed, inGroup ?? (marker.Case == RpWaitCase.Warband),
            battlegroundArrival);

    // 2.4, section 4: counting as waiting has no clock. No time goes in but the time left, so the turns a waiting bot
    // spends fighting, casting or rebuffing, when no hook runs, never let it charge or be recruited. It counts 60 s
    // after its wait started, 5 min after on a server whose rp_worth_seconds is 600, and in its last millisecond, at
    // its spot or 3,000 from it in its wait's region, where a fight took it.
    [TestCase(RpWaitCase.Frontier)]
    [TestCase(RpWaitCase.Siege)]
    [TestCase(RpWaitCase.Warband)]
    [TestCase(RpWaitCase.Battleground)]
    public void AWaitingBotCountsWithNoClock(RpWaitCase waitCase)
    {
        RpWaitMarker waiting = Waiting(waitCase);
        long minuteLater = RpTimerWait.WorthlessForMilliseconds(DeathTick, waiting.Started + 60_000, RpWorthSeconds);
        long fiveMinutesLater = RpTimerWait.WorthlessForMilliseconds(DeathTick, waiting.Started + 300_000, 600);
        Assert.That(minuteLater, Is.EqualTo(220_000));
        Assert.That(fiveMinutesLater, Is.EqualTo(280_000));

        var foughtAway = new Vector3(waiting.Spot.X + 3_000, waiting.Spot.Y, waiting.Spot.Z);
        foreach (long timeLeft in new[] { minuteLater, fiveMinutesLater, 1L })
        {
            Assert.That(Counts(waiting, timeLeft: timeLeft), Is.True);
            Assert.That(Counts(waiting, timeLeft: timeLeft, position: foughtAway), Is.True);
        }
    }

    // 2.4: every part must hold, so each mismatch alone stops a wait counting, whatever its case: the switch off
    // (section 6), no marker (a resurrected bot, a PvE goal), a marker for another death (killed again: the count is
    // raised before the Dying handler runs), time left 0 (worth points: it charges what it sees, section 4), another
    // region or assignment id than its wait's (hook 3 ends it on its next turn), a player's group (3.8), or the marker
    // Left (the wait ended).
    [TestCase("switch off")]
    [TestCase("no marker")]
    [TestCase("another death")]
    [TestCase("time left 0")]
    [TestCase("another region")]
    [TestCase("another assignment id")]
    [TestCase("player-led")]
    [TestCase("Left")]
    public void EachMismatchStopsItCounting(string mismatch)
    {
        foreach (RpWaitCase waitCase in EveryWaitCase)
        {
            RpWaitMarker waiting = Waiting(waitCase);
            Assert.That(Counts(waiting), Is.True, $"{waitCase}");
            bool counts = mismatch switch
            {
                "switch off" => Counts(waiting, enabled: false),
                "no marker" => RpTimerWait.IsWaiting(true, null, 3, TimeLeft, waiting.Region, waiting.Spot,
                    waiting.AssignmentId, false, waitCase == RpWaitCase.Warband, null),
                "another death" => Counts(waiting, deathCount: 4),
                "time left 0" => Counts(waiting, timeLeft: 0),
                "another region" => Counts(waiting, region: CamelotRegion),
                "another assignment id" => Counts(waiting, assignmentId: "albion-40-13-RvR"),
                "player-led" => Counts(waiting, playerLed: true),
                "Left" => Counts(waiting with { Phase = RpWaitPhase.Left }),
                _ => throw new ArgumentOutOfRangeException(nameof(mismatch)),
            };
            Assert.That(counts, Is.False, $"{waitCase}");
        }
    }

    // 2.4: a warband wait counts only while the bot is still in a group (a warband that disbands mid-wait ends its
    // wait, section 1). The group matters for no other wait: a frontier, siege or battleground wait, and a warband
    // member's wait converted to a siege wait (3.4), count in a group (a siege party's merge, section 4) or out of one.
    [Test]
    public void AWaitingWarbandWithNoGroupDoesNotCount()
    {
        RpWaitMarker held = Waiting(RpWaitCase.Warband);
        Assert.That(Counts(held, inGroup: true), Is.True);
        Assert.That(Counts(held, inGroup: false), Is.False);

        RpWaitMarker converted = held with { Case = RpWaitCase.Siege, EventKeepId = "rvr-keep-50", Started = Now };
        RpWaitMarker[] others =
        {
            Waiting(RpWaitCase.Frontier), Waiting(RpWaitCase.Siege), Waiting(RpWaitCase.Battleground), converted,
        };
        foreach (RpWaitMarker waiting in others)
        {
            Assert.That(Counts(waiting, inGroup: false), Is.True, $"{waiting.Case}");
            Assert.That(Counts(waiting, inGroup: true), Is.True, $"{waiting.Case}");
        }
    }

    // 2.4, 3.1: a battleground bot released outside (here in Camelot) counts from the moment the teleporter lands it,
    // before its first look, so the threat scan of its first think inside doesn't charge an enemy it only sees: in
    // any battleground region, within 2,500 of its realm's arrival point there (horizontally: 400 higher). Not with
    // no arrival known, not in another region than a battleground's with one, and not yet at its release point.
    [TestCase(0f, true)]
    [TestCase(2_500f, true)]
    [TestCase(2_501f, false)]
    [TestCase(2_600f, false)]
    public void AReleasedBotNearItsBattlegroundArrivalCounts(float away, bool counts)
    {
        RpWaitMarker released = ReleasedForTheBattleground();
        var standing = new Vector3(AlbionArrival.X, AlbionArrival.Y - away, AlbionArrival.Z + 400);
        for (ushort battleground = RpTimerWait.FirstBattlegroundRegion;
             battleground <= RpTimerWait.LastBattlegroundRegion; battleground++)
        {
            Assert.That(Counts(released, region: battleground, position: standing, battlegroundArrival: AlbionArrival),
                Is.EqualTo(counts), $"region {battleground}");
            Assert.That(Counts(released, region: battleground, position: standing), Is.False);
        }

        Assert.That(Counts(released, region: 1, position: standing, battlegroundArrival: AlbionArrival), Is.False);
        Assert.That(Counts(released), Is.False);
    }

    // 2.4, 3.2: a bot released at a bind in its own frontier (Albion's, Midgard's or Hibernia's) counts before its
    // first look while it stands within 750 of its release point there (horizontally: 300 lower), the first look's own
    // gate; not in another region at the same coordinates.
    [TestCase(0f, true)]
    [TestCase(750f, true)]
    [TestCase(751f, false)]
    [TestCase(800f, false)]
    public void AReleasedBotNearItsFrontierBindCounts(float away, bool counts)
    {
        var standing = new Vector3(Bind.X + away, Bind.Y, Bind.Z - 300);
        ushort[] frontiers = { RpTimerWait.AlbionFrontier, RpTimerWait.MidgardFrontier, RpTimerWait.HiberniaFrontier };
        foreach (ushort frontier in frontiers)
        {
            RpWaitMarker released = Released() with { ReleaseRegion = frontier, Region = frontier };
            Assert.That(Counts(released, position: standing), Is.EqualTo(counts), $"region {frontier}");

            ushort another = frontier == RpTimerWait.AlbionFrontier
                ? RpTimerWait.MidgardFrontier
                : RpTimerWait.AlbionFrontier;
            Assert.That(Counts(released, region: another, position: standing), Is.False);
        }
    }

    // 2.4, section 1: a frontier invader, or an attacker of a keep in an enemy frontier, releases in its capital
    // (Camelot, Jordheim or Tir na Nog: regions 10, 101 and 201; Camelot's point serves for each, only the region
    // matters), never in the frontier of its fight. So its Released marker never counts: not at its bind in the
    // capital, and not later in any frontier, at its release point's coordinates or at a frontier bind.
    [Test]
    public void AnInvadersReleasedMarkerNeverCounts()
    {
        ushort[] frontiers = { RpTimerWait.AlbionFrontier, RpTimerWait.MidgardFrontier, RpTimerWait.HiberniaFrontier };
        foreach (ushort capital in new ushort[] { CamelotRegion, 101, 201 })
        {
            RpWaitMarker released = ReleasedInCamelot() with { ReleaseRegion = capital, Region = capital };
            Assert.That(Counts(released), Is.False, $"region {capital}");
            foreach (ushort frontier in frontiers)
            {
                Assert.That(Counts(released, region: frontier), Is.False);
                Assert.That(Counts(released, region: frontier, position: Bind), Is.False);
            }
        }

        Assert.That(Counts(Released()), Is.True);
    }

    // 2.4: a Released marker counts under the same conditions as a wait: not with its time left at 0 (worth points
    // already), for an older death (killed again before its first look), with another assignment id, in a player's
    // group, or with the switch off; at a frontier bind or on a battleground arrival point alike.
    [Test]
    public void AReleasedMarkerOtherwiseOffDoesNotCount()
    {
        RpWaitMarker atBind = Released();
        Assert.That(Counts(atBind), Is.True);
        Assert.That(Counts(atBind, timeLeft: 0), Is.False);
        Assert.That(Counts(atBind, deathCount: 4), Is.False);
        Assert.That(Counts(atBind, assignmentId: "albion-40-13-RvR"), Is.False);
        Assert.That(Counts(atBind, playerLed: true), Is.False);
        Assert.That(Counts(atBind, enabled: false), Is.False);

        // The battleground bot landed on its realm's arrival point in Thidranki, its first look still to come.
        RpWaitMarker landed = ReleasedForTheBattleground();
        bool Landed(bool enabled = true, int deathCount = 3, long timeLeft = TimeLeft, string assignmentId = null,
            bool playerLed = false) =>
            Counts(landed, enabled, deathCount, timeLeft, Thidranki, AlbionArrival, assignmentId, playerLed,
                battlegroundArrival: AlbionArrival);
        Assert.That(Landed(), Is.True);
        Assert.That(Landed(timeLeft: 0), Is.False);
        Assert.That(Landed(deathCount: 4), Is.False);
        Assert.That(Landed(assignmentId: "albion-20-13-Battleground"), Is.False);
        Assert.That(Landed(playerLed: true), Is.False);
        Assert.That(Landed(enabled: false), Is.False);
    }

    // 3.7, 2.4: a bot killed while waiting, or while released before its first look, stops counting at once: its
    // death count is raised before the Dying handler runs, and the handler then latches the old marker Left.
    // Resurrected where it fell (no release), it has no marker for the new death and charges and is recruited as any
    // bot; released instead, hook 3 notes the new death and it counts again at its bind.
    [Test]
    public void AMarkerLatchedByADeathDoesNotCount()
    {
        RpWaitMarker[] markers =
        {
            Waiting(RpWaitCase.Frontier), Waiting(RpWaitCase.Siege), Waiting(RpWaitCase.Warband), Released(),
        };
        foreach (RpWaitMarker before in markers)
        {
            RpWaitSlot slot = SlotWith(before);
            Assert.That(Counts(slot.Current), Is.True);
            Assert.That(Counts(slot.Current, deathCount: 4), Is.False);

            slot.Apply(marker => RpTimerWait.Died(marker, 4));
            RpWaitMarker left = slot.Current;
            Assert.That(left.Phase, Is.EqualTo(RpWaitPhase.Left));
            Assert.That(Counts(left, deathCount: 4), Is.False);
            Assert.That(Counts(left), Is.False);

            AssertKept(ReleaseTurn(left, deathCount: 4, returning: false), left);
            Assert.That(Counts(left, deathCount: 4), Is.False);

            RpWaitChange noted = ReleaseTurn(left, deathCount: 4);
            Assert.That(slot.TrySwap(noted.Before, noted.Next), Is.True);
            Assert.That(Counts(slot.Current, deathCount: 4), Is.True);
        }
    }
}
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/Tests/UnitTests/UT_RpTimerWait.cs (1 block(s))`.

- [ ] **Step 2: Run them and watch them fail.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWait."`
Expected: the build fails (exit code 1) and no test runs. 2 errors, both `CS0117`, a member missing from the class
`RpTimerWait`: `IsWaiting` in `Counts` and in `EachMismatchStopsItCounting`'s no-marker row, each with the file's
absolute path and the project at the end of the line:

```
source/server/Tests/UnitTests/UT_RpTimerWait.cs(1797,21): error CS0117: 'RpTimerWait' does not contain a definition for 'IsWaiting'
source/server/Tests/UnitTests/UT_RpTimerWait.cs(1847,44): error CS0117: 'RpTimerWait' does not contain a definition for 'IsWaiting'
```

- [ ] **Step 3: Implement.** Add `IsWaiting` after `WarbandMarks`, before the class's closing brace, with exactly the
code below. It follows the rule comment above it: every part that applies to any marker first (the switch on, a
marker for this death, time left above 0, the same assignment id, not player-led), then by phase. A Waiting marker
counts in its wait's region, wherever a fight took the bot there, and a warband marker only while the bot is grouped.
A Released marker counts where its first look will happen: in a battleground region within 2,500 of the arrival the
wiring passes (none passed: no), or in its release region, when that is a frontier region, within 750 of its release
point; both distances horizontal. A Left marker never counts. No clock is read:

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs <<'EDIT'
<<<<<<< OLD
            changes[i] = WarbandMark(gate, rendezvousRegion, members[i], sessionId, now);
        return changes;
    }
}
=======
            changes[i] = WarbandMark(gate, rendezvousRegion, members[i], sessionId, now);
        return changes;
    }

    // 2.4: counts as waiting (hooks 5 and 6). All of: enabled; marker for deathCount; timeLeft > 0; assignmentId ==
    // marker.AssignmentId; !playerLed; and either (Waiting, region == marker.Region, and inGroup for a Warband marker)
    // or (Released, and: in a battleground region with battlegroundArrival known and Distance2D(position, it) <=
    // 2,500; or marker.ReleaseRegion a frontier region, region == marker.ReleaseRegion and Distance2D(position,
    // ReleasePoint) <= 750). Left: false.
    public static bool IsWaiting(bool enabled, RpWaitMarker marker, int deathCount, long timeLeft, ushort region,
        Vector3 position, string assignmentId, bool playerLed, bool inGroup, Vector3? battlegroundArrival)
    {
        if (!enabled || marker == null || marker.DeathCount != deathCount || timeLeft <= 0 ||
            assignmentId != marker.AssignmentId || playerLed)
            return false;

        // No clock: a wait counts in its region wherever a fight took the bot (a warband member while still grouped);
        // a release counts where its first look will happen, so the threat scan before that look holds too.
        return marker.Phase switch
        {
            RpWaitPhase.Waiting => region == marker.Region && (marker.Case != RpWaitCase.Warband || inGroup),
            RpWaitPhase.Released =>
                (IsBattlegroundRegion(region) && battlegroundArrival is Vector3 arrival &&
                 Distance2D(position, arrival) <= ArrivalGate) ||
                (IsFrontierRegion(marker.ReleaseRegion) && region == marker.ReleaseRegion &&
                 Distance2D(position, marker.ReleasePoint) <= BindGate),
            _ => false,
        };
    }
}
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs (1 block(s))`.

- [ ] **Step 4: Run them and watch them pass.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWait."`
Expected: `Passed!  - Failed:     0, Passed:   160, Skipped:     0, Total:   160` (exit code 0; no warning names
`RpTimerWait.cs` or `UT_RpTimerWait.cs`). 160 = Tasks 1-5's 136 + this task's 24: 4 `[Test]` methods and 20
`[TestCase]` rows (`AWaitingBotCountsWithNoClock` 4, `EachMismatchStopsItCounting` 8,
`AReleasedBotNearItsBattlegroundArrivalCounts` 4, `AReleasedBotNearItsFrontierBindCounts` 4).

Run: `git diff --stat`
Expected: only the two files, `RpTimerWait.cs` with 26 lines added and `UT_RpTimerWait.cs` with 226, then
`2 files changed, 252 insertions(+)`.

- [ ] **Step 5: Commit.**

```bash
git add source/server/GameServer/scripts/hearthdaoc/RpTimerWait.cs source/server/Tests/UnitTests/UT_RpTimerWait.cs
git commit -F - <<'EOF'
feat(rp-wait): what counts as waiting

Recruiting and the threat scan ask whether a bot is waiting: a wait for this death, still worth nothing, with the
same assignment, not in a player's group, in its wait's region (a warband member still grouped), or released and
standing where its first look will happen. There is no clock, so fights, casts and rebuffs never let a waiting bot
charge or be recruited.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

Expected: `2 files changed, 252 insertions(+)`.

---

### Task 7: The `bot_rp_timer_wait` switch, on in HearthDAoC

**Files:**
- Create: `source/server/GameServer/scripts/hearthdaoc/RpTimerWaitScript.cs` (the usings, the header comment, the
  class and the `[ServerProperty]` field; Tasks 8 and 9 add the rest)
- Create: `source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs` (the test double server and
  one test)
- Create: `deploy/tests/test_rp_timer_wait.py` (the module docstring, the imports, every path constant and helper, and
  its first four classes)
- Modify: `deploy/bin/server_properties.py`, `deploy/entrypoint.sh`, `deploy/compose.yml`, `deploy/.env.example`,
  `deploy/HANDOFF.md` (`HEARTHDAOC_BOT_RP_TIMER_WAIT` to `bot_rp_timer_wait`, default on, documented)
- Modify: `deploy/tests/test_server_properties.py`, `deploy/tests/test_si_start_choice.py` (their CLI calls and
  expected output follow the new required argument)
- Modify: `.github/workflows/server-image.yml`, `deploy/tests/test_workflows.py` (CI runs `UT_RpTimerWaitScript`)
- Test: `source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs`, `deploy/tests/test_rp_timer_wait.py`,
  `deploy/tests/test_server_properties.py`, `deploy/tests/test_si_start_choice.py`, `deploy/tests/test_workflows.py`

**Spec:** section 6 (the switch), 10.1 ("Wiring": the declaration; "CI"), 10.3 (the deploy tests, and the existing
lines that change and stay), 11 (`HANDOFF.md`, `.env.example`).

**Interfaces:**
- Consumes: `ServerPropertyAttribute` (`DOL.GS.ServerProperties`: `Category`, `Key`, `Description`, `DefaultValue`);
  in the test double, `GameServer.LoadTestDouble`, `NormalServerRules`, `IObjectDatabase`, `GameLoop.GameLoopTime`,
  `Properties.RP_WORTH_SECONDS` and `PropertyCollection`; in `server_properties.py`, `SI_VALUES`, `PropertyError` and
  `set_property(db, key, value, category, description, default)`; in the deploy tests,
  `deploy/tests/test_server_properties.py`'s `SCHEMA` and `row`.
- Produces:
  - in `namespace DOL.GS.HearthDAoC`, `public static class RpTimerWaitScript` with
    `[ServerProperty("server", "bot_rp_timer_wait", "Released gamebots wait at a safe spot until their trip back to the fight ends as their rp_worth_seconds timer does, so they come back worth realm points", false)] public static bool BOT_RP_TIMER_WAIT;`
    (Tasks 8 and 9 add their members after it);
  - in `deploy/bin/server_properties.py`: `RP_WAIT_KEY = "bot_rp_timer_wait"`, `RP_WAIT_DESCRIPTION` (the same
    description), `RP_WAIT_DEFAULT = "False"`, `def bot_rp_timer_wait_value(spec)` (`'on'` -> `'True'`, `'off'` ->
    `'False'`, any case; anything else raises `PropertyError("HEARTHDAOC_BOT_RP_TIMER_WAIT must be on or off, got
    '…'")`), and the required argument `--bot-rp-timer-wait`, declared after `--si-start-choice`, checked before any
    write, printing `Bot realm point timer wait: on` (or `off`) when it changes the row;
  - `HEARTHDAOC_BOT_RP_TIMER_WAIT`, default `on`, in `deploy/compose.yml`, `deploy/entrypoint.sh` and
    `deploy/.env.example`;
  - for Tasks 8 and 9, in `UT_RpTimerWaitScript`: `SaveGlobals`/`RestoreGlobals` (the test double server; the switch,
    `RP_WORTH_SECONDS` and `GameLoopTime` saved and restored), `SetTime(long)` and `Bot()` (a gamebot without its
    constructor, with real `TempProperties`); in `test_rp_timer_wait.py`: `read`, `source`, `between`, `marked`,
    `cs_files` and the path constants (`ROOT`, `GAME_SERVER`, `FORK`, `SCRIPT_CS`, `DECISIONS_CS`, `CONTROLLER_CS`,
    `WBC`, `BG`, `FT`, `GC`, `KEEP_TRAVEL`, `SIEGE`, `ARPR`).

- [ ] **Step 1: Write the failing tests.** Create `source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs` with
exactly the code below: a test double server, which every later wiring test needs before it makes
a `GameBot`, and the switch's declaration, read back the way the server finds it (`ServerProperties.AllDomainProperties`
reads `GetFields()`, so only public fields, then keeps the static ones):

```csharp
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
```

Create `deploy/tests/test_rp_timer_wait.py` with exactly the code below: the switch's value check, the entrypoint's
own command run against a scratch world (default on, `OFF`, and a bad value that stops the start before any write),
compose, `.env.example` and `HANDOFF.md`, and the C# declaration's description against `server_properties.py`'s.
The helpers and path constants that Tasks 8-11's source checks use are in from the start. Later classes go before
`if __name__ == "__main__":`, with two blank lines before each:

```python
"""Gamebots come back worth realm points, stage 1 (spec docs/fork/specs/2026-10-13-rp-timer-waits-design.md).

The switch goes .env -> compose.yml -> entrypoint.sh -> server_properties.py -> the bot_rp_timer_wait server
property, default on at every step (hdc update appends the new .env.example line to an existing .env). The
decisions are unit-tested (UT_RpTimerWait, UT_RpTimerWaitScript); the six hooks in upstream files, the handlers'
registration and the upstream facts the waits mirror need a live server, so these check the source.
"""
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.dirname(HERE)
ROOT = os.path.dirname(DEPLOY)
BIN = os.path.join(DEPLOY, "bin")
sys.path.insert(0, BIN)

import server_properties as sp  # noqa: E402
from tests.test_server_properties import SCHEMA, row  # noqa: E402

GAME_SERVER = os.path.join(ROOT, "source", "server", "GameServer")
FORK = os.path.join(GAME_SERVER, "scripts", "hearthdaoc")
SCRIPT_CS = os.path.join(FORK, "RpTimerWaitScript.cs")
DECISIONS_CS = os.path.join(FORK, "RpTimerWait.cs")
CONTROLLER_CS = os.path.join(FORK, "RpTimerWaitController.cs")
BOTS = os.path.join(GAME_SERVER, "bots", "autonomous")
WBC = os.path.join(BOTS, "AutonomousWorldBotController.cs")
BG = os.path.join(BOTS, "AutonomousWorldBotController.Battleground.cs")
FT = os.path.join(BOTS, "AutonomousWorldBotController.FrontierThreat.cs")
GC = os.path.join(BOTS, "AutonomousBotGroupCoordinator.cs")
KEEP_TRAVEL = os.path.join(BOTS, "AutonomousWorldBotController.KeepTravel.cs")
SIEGE = os.path.join(BOTS, "AutonomousWorldBotController.Siege.cs")
ARPR = os.path.join(BOTS, "AutonomousBotRealmPointRewards.cs")


def read(name):
    with open(os.path.join(DEPLOY, name), encoding="utf-8") as f:
        return f.read()


def source(path):
    """A C# source file's text (upstream files may start with a BOM)."""
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        return f.read()


def between(text, start, end):
    """The text from the first start up to the first end after it."""
    body = text[text.index(start):]
    return body[:body.index(end)]


def marked(test, body, call):
    """The body calls the fork once, with a // HearthDAoC: comment on the line above the call."""
    test.assertEqual(body.count(call), 1, call)
    above = body[:body.index(call)].rsplit("\n", 2)[-2]
    test.assertIn("// HearthDAoC:", above, call)


def cs_files(top):
    """Every .cs file under top, sorted."""
    found = []
    for folder, _, names in os.walk(top):
        found.extend(os.path.join(folder, name) for name in names if name.endswith(".cs"))
    return sorted(found)


class SwitchValueTests(unittest.TestCase):
    def test_on_and_off_in_any_case_become_true_and_false(self):
        for spec, expected in (("on", "True"), ("ON", "True"), ("On", "True"),
                               ("off", "False"), ("OFF", "False"), ("oFf", "False")):
            with self.subTest(spec=spec):
                self.assertEqual(sp.bot_rp_timer_wait_value(spec), expected)

    def test_other_values_are_refused(self):
        for bad in ("", "yes", "no", "true", "false", "1", "0", "none", "onn", " on", "off "):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                    sp.PropertyError, f"^HEARTHDAOC_BOT_RP_TIMER_WAIT must be on or off, got {re.escape(repr(bad))}$"):
                sp.bot_rp_timer_wait_value(bad)

    def test_the_property_matches_the_server_declaration(self):
        self.assertEqual((sp.RP_WAIT_KEY, sp.RP_WAIT_DEFAULT), ("bot_rp_timer_wait", "False"))
        self.assertNotIn('"', sp.RP_WAIT_DESCRIPTION)
        self.assertNotIn("\\", sp.RP_WAIT_DESCRIPTION)


class EntrypointTests(unittest.TestCase):
    """Runs the entrypoint's own server_properties.py command against a scratch world."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.tmp.name, "world"))
        self.db = os.path.join(self.tmp.name, "world", "opendaoc.sqlite3.db")
        with sqlite3.connect(self.db) as c:
            c.execute(SCHEMA)
        lines = read("entrypoint.sh").replace("\\\n", " ").splitlines()
        commands = [line for line in lines if line.startswith('python3 "$BIN/server_properties.py"')]
        self.assertEqual(len(commands), 1, "the entrypoint runs server_properties.py once")
        self.command = commands[0]

    def tearDown(self):
        self.tmp.cleanup()

    def run_entrypoint_line(self, **env):
        script = f"set -euo pipefail\nBIN={shlex.quote(BIN)}\nDATA={shlex.quote(self.tmp.name)}\n{self.command}\n"
        base = {k: v for k, v in os.environ.items() if not k.startswith("HEARTHDAOC_")}
        return subprocess.run(["bash", "-c", script], env={**base, **env}, capture_output=True, text=True)

    def test_passes_the_setting_with_default_on(self):
        self.assertIn('--bot-rp-timer-wait "${HEARTHDAOC_BOT_RP_TIMER_WAIT-on}"', self.command)
        r = self.run_entrypoint_line()
        self.assertEqual((r.returncode, r.stdout, r.stderr),
                         (0, "GM-only commands: /tele;/tc\nShrouded Isles start choice: on\nBot realm point timer wait: on\n", ""))
        self.assertEqual(row(self.db, sp.RP_WAIT_KEY), ("server", sp.RP_WAIT_DESCRIPTION, "False", "True"))

    def test_off_in_any_case_turns_it_off(self):
        self.run_entrypoint_line()
        r = self.run_entrypoint_line(HEARTHDAOC_BOT_RP_TIMER_WAIT="OFF")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "Bot realm point timer wait: off\n", ""))
        self.assertEqual(row(self.db, sp.RP_WAIT_KEY)[3], "False")

    def test_a_bad_value_stops_the_start(self):
        for bad in ("maybe", ""):
            with self.subTest(bad=bad):
                r = self.run_entrypoint_line(HEARTHDAOC_BOT_RP_TIMER_WAIT=bad)
                self.assertEqual(r.returncode, 2)
                self.assertEqual(r.stderr, f"ERROR: HEARTHDAOC_BOT_RP_TIMER_WAIT must be on or off, got {bad!r}\n")
                self.assertIsNone(row(self.db, sp.RP_WAIT_KEY))
                self.assertIsNone(row(self.db, sp.OVERRIDES_KEY))  # checked before any write: nothing at all
                self.assertIsNone(row(self.db, sp.SI_KEY))


class SettingDocsTests(unittest.TestCase):
    def test_compose_passes_the_setting_with_default_on(self):
        environment = read("compose.yml").split("\n    environment:\n", 1)[1].split("\n    volumes:\n", 1)[0]
        self.assertIn("\n      HEARTHDAOC_BOT_RP_TIMER_WAIT: ${HEARTHDAOC_BOT_RP_TIMER_WAIT-on}\n", environment + "\n")

    def test_env_example_documents_the_setting_default_on(self):
        lines = read(".env.example").splitlines()
        self.assertEqual([line for line in lines if line.startswith("HEARTHDAOC_BOT_RP_TIMER_WAIT")],
                         ["HEARTHDAOC_BOT_RP_TIMER_WAIT=on"])
        i = lines.index("HEARTHDAOC_BOT_RP_TIMER_WAIT=on")
        comment = []
        while i > 0 and lines[i - 1].startswith("#"):
            i -= 1
            comment.insert(0, lines[i])
        self.assertIn("realm points", " ".join(comment))
        self.assertIn("off =", " ".join(comment))

    def test_handoff_lists_the_setting(self):
        handoff = read("HANDOFF.md")
        self.assertIn("`HEARTHDAOC_BOT_RP_TIMER_WAIT` (default `on`", handoff)
        self.assertIn("`HEARTHDAOC_BOT_RP_TIMER_WAIT=on`", handoff)  # what ./hdc update adds to an existing .env


class ServerDeclarationTests(unittest.TestCase):
    def test_server_declares_the_property_with_the_same_description(self):
        with open(SCRIPT_CS, encoding="utf-8") as f:
            found = re.findall(r'\[ServerProperty\(\s*"([^"]*)",\s*"bot_rp_timer_wait",\s*"([^"]*)",\s*(\w+)\s*\)\]', f.read())
        self.assertEqual(found, [("server", sp.RP_WAIT_DESCRIPTION, "false")])


if __name__ == "__main__":
    unittest.main()
```

Then the existing deploy tests follow the new required argument. In `test_server_properties.py`, every CLI call gains
`--bot-rp-timer-wait` except the one that tests a missing argument (argparse names missing required arguments in the
order they were declared, so `--si-start-choice` is still named first), and the two runs on a world with no
`bot_rp_timer_wait` row expect its line:

```bash
python3 /tmp/hdc-edit.py deploy/tests/test_server_properties.py <<'EDIT'
<<<<<<< OLD
        r = run_cli(self.db, "--gm-only-commands", "/tele;/tc", "--si-start-choice", "on")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(value(self.db, sp.OVERRIDES_KEY), "/tele=2;/tc=2")
        self.assertEqual(run_cli(self.db, "--gm-only-commands", "tele", "--si-start-choice", "on").returncode, 2)
=======
        r = run_cli(self.db, "--gm-only-commands", "/tele;/tc", "--si-start-choice", "on", "--bot-rp-timer-wait", "on")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(value(self.db, sp.OVERRIDES_KEY), "/tele=2;/tc=2")
        self.assertEqual(run_cli(self.db, "--gm-only-commands", "tele", "--si-start-choice", "on",
                                 "--bot-rp-timer-wait", "on").returncode, 2)
>>>>>>> NEW
<<<<<<< OLD
        r = run_cli(self.db, "--gm-only-commands", "none", "--si-start-choice", "ON")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "GM-only commands: none\nShrouded Isles start choice: on\n", ""))
        self.assertEqual(row(self.db, sp.SI_KEY), ("server", sp.SI_DESCRIPTION, "False", "True"))
        r = run_cli(self.db, "--gm-only-commands", "none", "--si-start-choice", "Off")
=======
        r = run_cli(self.db, "--gm-only-commands", "none", "--si-start-choice", "ON", "--bot-rp-timer-wait", "on")
        self.assertEqual((r.returncode, r.stdout, r.stderr),
                         (0, "GM-only commands: none\nShrouded Isles start choice: on\nBot realm point timer wait: on\n", ""))
        self.assertEqual(row(self.db, sp.SI_KEY), ("server", sp.SI_DESCRIPTION, "False", "True"))
        r = run_cli(self.db, "--gm-only-commands", "none", "--si-start-choice", "Off", "--bot-rp-timer-wait", "on")
>>>>>>> NEW
<<<<<<< OLD
        run_cli(self.db, "--gm-only-commands", "/tele;/tc", "--si-start-choice", "off")
        r = run_cli(self.db, "--gm-only-commands", "/tele;/tc", "--si-start-choice", "OFF")
=======
        run_cli(self.db, "--gm-only-commands", "/tele;/tc", "--si-start-choice", "off", "--bot-rp-timer-wait", "off")
        r = run_cli(self.db, "--gm-only-commands", "/tele;/tc", "--si-start-choice", "OFF", "--bot-rp-timer-wait", "OFF")
>>>>>>> NEW
<<<<<<< OLD
        r = run_cli(self.db, "--gm-only-commands", "/tele;/tc", "--si-start-choice", "yes")
=======
        r = run_cli(self.db, "--gm-only-commands", "/tele;/tc", "--si-start-choice", "yes", "--bot-rp-timer-wait", "on")
>>>>>>> NEW
<<<<<<< OLD
        r = run_cli(self.db, "--gm-only-commands", "/tele;/tc", "--si-start-choice", "on")
        self.assertEqual((r.returncode, r.stdout), (0, "Shrouded Isles start choice: on\n"), r.stderr)
=======
        r = run_cli(self.db, "--gm-only-commands", "/tele;/tc", "--si-start-choice", "on", "--bot-rp-timer-wait", "on")
        self.assertEqual((r.returncode, r.stdout), (0, "Shrouded Isles start choice: on\nBot realm point timer wait: on\n"),
                         r.stderr)
>>>>>>> NEW
EDIT
```

Expected: `edited deploy/tests/test_server_properties.py (5 block(s))`.

`test_si_start_choice.py`'s entrypoint run on an empty world prints the new line too (its other two runs stay: the
new row is already on, and a bad Shrouded Isles value stops before any write):

```bash
python3 /tmp/hdc-edit.py deploy/tests/test_si_start_choice.py <<'EDIT'
<<<<<<< OLD
                         (0, "GM-only commands: /tele;/tc\nShrouded Isles start choice: on\n", ""))
=======
                         (0, "GM-only commands: /tele;/tc\nShrouded Isles start choice: on\nBot realm point timer wait: on\n", ""))
>>>>>>> NEW
EDIT
```

Expected: `edited deploy/tests/test_si_start_choice.py (1 block(s))`.

And the workflow check pins the new class: its copy of CI's filter string, and its list of names (each must be a file
holding `public sealed class UT_X`, which the new test file is). CI's own filter follows in Step 3.

```bash
python3 /tmp/hdc-edit.py deploy/tests/test_workflows.py <<'EDIT'
<<<<<<< OLD
                     '|FullyQualifiedName~UT_RpTimerWait"')
=======
                     '|FullyQualifiedName~UT_RpTimerWait|FullyQualifiedName~UT_RpTimerWaitScript"')
>>>>>>> NEW
<<<<<<< OLD
                                 "UT_RpTimerWait"])
=======
                                 "UT_RpTimerWait", "UT_RpTimerWaitScript"])
>>>>>>> NEW
EDIT
```

Expected: `edited deploy/tests/test_workflows.py (2 block(s))`.

- [ ] **Step 2: Run them and watch them fail.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWaitScript."`
Expected: the build fails (exit code 1) and no test runs. 3 errors: `CS0103` twice (the switch saved in `SaveGlobals`
and restored in `RestoreGlobals`) and `CS0246` once (`typeof(RpTimerWaitScript)` in the test), each with the file's
absolute path and the project at the end of the line:

```
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(55,24): error CS0103: The name 'RpTimerWaitScript' does not exist in the current context
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(63,9): error CS0103: The name 'RpTimerWaitScript' does not exist in the current context
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(85,45): error CS0246: The type or namespace name 'RpTimerWaitScript' could not be found (are you missing a using directive or an assembly reference?)
```

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_rp_timer_wait.py`
Expected: `Ran 10 tests` and `FAILED (failures=7, errors=19)`. The errors, counted per subtest: 17 `AttributeError:
module 'server_properties' has no attribute 'bot_rp_timer_wait_value'` (`SwitchValueTests`' two value tests, 6 + 11
subtests), 1 `AttributeError: ... no attribute 'RP_WAIT_KEY'` (`test_the_property_matches_the_server_declaration`)
and 1 `FileNotFoundError` naming `source/server/GameServer/scripts/hearthdaoc/RpTimerWaitScript.cs`
(`test_server_declares_the_property_with_the_same_description`). The failures: `EntrypointTests`' three (4:
`test_a_bad_value_stops_the_start` fails once per subtest, `maybe` and `''`, with `0 != 2`, since nothing reads the
variable yet; `test_off_in_any_case_turns_it_off` prints nothing; `test_passes_the_setting_with_default_on` finds no
`--bot-rp-timer-wait` in the entrypoint's command) and `SettingDocsTests`' three (compose, `.env.example`,
`HANDOFF.md`).

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_server_properties.py`
Expected: `FAIL:` for `test_cli`, `test_cli_writes_the_si_start_choice_as_true_or_false`,
`test_cli_prints_nothing_when_nothing_changes` and `test_cli_refuses_a_bad_si_start_choice_and_writes_nothing`, each
because the CLI stops with exit code 2 and `server_properties.py: error: unrecognized arguments: --bot-rp-timer-wait
on` (or `OFF`), then `Ran 15 tests` and `FAILED (failures=4, skipped=1)` (`test_shipped_world` skips without
`HDC_TEST_WORLD`).

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_si_start_choice.py`
Expected: `FAIL: test_passes_the_setting_with_default_on (tests.test_si_start_choice.EntrypointTests...)` (the output
has no `Bot realm point timer wait: on` line yet), then `Ran 8 tests` and `FAILED (failures=1, skipped=1)`.

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_workflows.py`
Expected: `FAIL: test_the_fork_server_unit_tests_run_with_the_pinned_filter` (CI's step does not name
`UT_RpTimerWaitScript` yet), then `Ran 17 tests` and `FAILED (failures=1)`.

- [ ] **Step 3: Implement.** Create `source/server/GameServer/scripts/hearthdaoc/RpTimerWaitScript.cs` with exactly
the code below: its usings (these five; Task 8 adds `using System.Globalization;`), header comment and class, with
the switch only. A world with no `bot_rp_timer_wait` row gets one from the attribute at the server's start, with
default and value `False` (off); `server_properties.py` gives a row it creates the same default (`RP_WAIT_DEFAULT`):

```csharp
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
```

`server_properties.py` gets the docstring's paragraph, the declaration's constants (next to the Shrouded Isles ones,
under a comment naming the C# file that must match), the value check, the required argument after
`--si-start-choice`, the check with the others before any write, and the write with its line, after the Shrouded
Isles one:

```bash
python3 /tmp/hdc-edit.py deploy/bin/server_properties.py <<'EDIT'
<<<<<<< OLD
Shrouded Isles town.
Only writes a property when its value differs, and prints a line for each one it changed.
=======
Shrouded Isles town.
HEARTHDAOC_BOT_RP_TIMER_WAIT (on or off, case ignored) becomes the bot_rp_timer_wait property (True or
False): a gamebot released after a death in RvR or a battleground then waits at a safe spot and comes back
just as it is worth realm points again.
Only writes a property when its value differs, and prints a line for each one it changed.
>>>>>>> NEW
<<<<<<< OLD
SI_VALUES = {"on": "True", "off": "False"}
=======
SI_VALUES = {"on": "True", "off": "False"}

# Must match the server's [ServerProperty("server", "bot_rp_timer_wait", RP_WAIT_DESCRIPTION, false)] in
# source/server/GameServer/scripts/hearthdaoc/RpTimerWaitScript.cs (deploy/tests/test_rp_timer_wait.py checks).
RP_WAIT_KEY = "bot_rp_timer_wait"
RP_WAIT_DESCRIPTION = ("Released gamebots wait at a safe spot until their trip back to the fight ends as their "
                       "rp_worth_seconds timer does, so they come back worth realm points")
RP_WAIT_DEFAULT = "False"  # the code default (off), as the server itself writes it
>>>>>>> NEW
<<<<<<< OLD
        raise PropertyError(f"HEARTHDAOC_SI_START_CHOICE must be on or off, got {spec!r}") from None
=======
        raise PropertyError(f"HEARTHDAOC_SI_START_CHOICE must be on or off, got {spec!r}") from None


def bot_rp_timer_wait_value(spec):
    """'on' -> 'True', 'off' -> 'False', in any case; anything else is refused."""
    try:
        return SI_VALUES[spec.lower()]
    except KeyError:
        raise PropertyError(f"HEARTHDAOC_BOT_RP_TIMER_WAIT must be on or off, got {spec!r}") from None
>>>>>>> NEW
<<<<<<< OLD
    ap.add_argument("--si-start-choice", required=True, help="on or off (case ignored)")
=======
    ap.add_argument("--si-start-choice", required=True, help="on or off (case ignored)")
    ap.add_argument("--bot-rp-timer-wait", required=True, help="on or off (case ignored)")
>>>>>>> NEW
<<<<<<< OLD
        si_start = si_start_value(a.si_start_choice)
=======
        si_start = si_start_value(a.si_start_choice)
        rp_wait = bot_rp_timer_wait_value(a.bot_rp_timer_wait)
>>>>>>> NEW
<<<<<<< OLD
        print(f"Shrouded Isles start choice: {a.si_start_choice.lower()}")
=======
        print(f"Shrouded Isles start choice: {a.si_start_choice.lower()}")
    if set_property(a.db, RP_WAIT_KEY, rp_wait, description=RP_WAIT_DESCRIPTION, default=RP_WAIT_DEFAULT):
        print(f"Bot realm point timer wait: {a.bot_rp_timer_wait.lower()}")
>>>>>>> NEW
EDIT
```

Expected: `edited deploy/bin/server_properties.py (6 block(s))`.

The entrypoint passes it on the continuation line, default on (`EntrypointTests` join continuation lines before they
look for the command):

```bash
python3 /tmp/hdc-edit.py deploy/entrypoint.sh <<'EDIT'
<<<<<<< OLD
# Single-player shortcuts that need GM rights on a shared server (command_plvl_overrides), and the
# Shrouded Isles start choice for new characters (si_start_choice). A bad value stops the start (exit 2).
python3 "$BIN/server_properties.py" --db "$DATA/world/opendaoc.sqlite3.db" --gm-only-commands "${HEARTHDAOC_GM_ONLY_COMMANDS-/tele;/tc}" \
    --si-start-choice "${HEARTHDAOC_SI_START_CHOICE-on}"
=======
# Single-player shortcuts that need GM rights on a shared server (command_plvl_overrides), the Shrouded
# Isles start choice for new characters (si_start_choice), and released gamebots waiting until they are worth
# realm points again (bot_rp_timer_wait). A bad value stops the start (exit 2).
python3 "$BIN/server_properties.py" --db "$DATA/world/opendaoc.sqlite3.db" --gm-only-commands "${HEARTHDAOC_GM_ONLY_COMMANDS-/tele;/tc}" \
    --si-start-choice "${HEARTHDAOC_SI_START_CHOICE-on}" --bot-rp-timer-wait "${HEARTHDAOC_BOT_RP_TIMER_WAIT-on}"
>>>>>>> NEW
EDIT
```

Expected: `edited deploy/entrypoint.sh (1 block(s))`.

```bash
python3 /tmp/hdc-edit.py deploy/compose.yml <<'EDIT'
<<<<<<< OLD
      HEARTHDAOC_SI_START_CHOICE: ${HEARTHDAOC_SI_START_CHOICE-on}
=======
      HEARTHDAOC_SI_START_CHOICE: ${HEARTHDAOC_SI_START_CHOICE-on}
      HEARTHDAOC_BOT_RP_TIMER_WAIT: ${HEARTHDAOC_BOT_RP_TIMER_WAIT-on}
>>>>>>> NEW
EDIT
```

Expected: `edited deploy/compose.yml (1 block(s))`.

`./hdc update` appends every `KEY=` line of `.env.example` that an existing `.env` lacks, so servers set up before
get it on:

```bash
python3 /tmp/hdc-edit.py deploy/.env.example <<'EDIT'
<<<<<<< OLD
HEARTHDAOC_SI_START_CHOICE=on
=======
HEARTHDAOC_SI_START_CHOICE=on
# on = a gamebot released after a death in RvR or a battleground waits at a safe spot (a bind of its realm, or
# its realm's arrival point in a battleground; a frontier warband at its border keep) and goes back so it arrives
# just as it is worth realm points again, 300 s after its last death. off = released gamebots go straight back,
# as before. Case is ignored.
HEARTHDAOC_BOT_RP_TIMER_WAIT=on
>>>>>>> NEW
EDIT
```

Expected: `edited deploy/.env.example (1 block(s))`.

`HANDOFF.md`'s settings paragraph and its `./hdc update` sentence:

```bash
python3 /tmp/hdc-edit.py deploy/HANDOFF.md <<'EDIT'
<<<<<<< OLD
whether to begin in its realm's Shrouded Isles town; `off` turns the question off); after
editing `.env`, `./hdc up` recreates the server with them.
=======
whether to begin in its realm's Shrouded Isles town; `off` turns the question off) and
`HEARTHDAOC_BOT_RP_TIMER_WAIT` (default `on`: a gamebot released after a death in RvR or a battleground waits
at a safe spot and comes back just as it is worth realm points again; `off` sends it straight back); after
editing `.env`, `./hdc up` recreates the server with them.
>>>>>>> NEW
<<<<<<< OLD
(it lists them; for example, the release with the Shrouded Isles start choice adds
`HEARTHDAOC_SI_START_CHOICE=on`). It always backs up the world first (`-pre-update` in `./hdc backups`).
=======
(it lists them; for example, the release with the Shrouded Isles start choice adds
`HEARTHDAOC_SI_START_CHOICE=on`, and the one with the realm point waits adds `HEARTHDAOC_BOT_RP_TIMER_WAIT=on`).
It always backs up the world first (`-pre-update` in `./hdc backups`).
>>>>>>> NEW
EDIT
```

Expected: `edited deploy/HANDOFF.md (2 block(s))`.

CI runs the new class (`~UT_RpTimerWait` already matches it; the spec lists both names):

```bash
python3 /tmp/hdc-edit.py .github/workflows/server-image.yml <<'EDIT'
<<<<<<< OLD
|FullyQualifiedName~UT_RpTimerWait"
=======
|FullyQualifiedName~UT_RpTimerWait|FullyQualifiedName~UT_RpTimerWaitScript"
>>>>>>> NEW
EDIT
```

Expected: `edited .github/workflows/server-image.yml (1 block(s))`.

- [ ] **Step 4: Run them and watch them pass.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWaitScript."`
Expected: `Passed!  - Failed:     0, Passed:     1, Skipped:     0, Total:     1` (exit code 0; no warning names
`RpTimerWaitScript.cs` or `UT_RpTimerWaitScript.cs`).

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_rp_timer_wait.py`
Expected: `Ran 10 tests` and `OK`.

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_server_properties.py`
Expected: `Ran 15 tests` and `OK (skipped=1)`.

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_si_start_choice.py`
Expected: `Ran 8 tests` and `OK (skipped=1)`.

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_workflows.py`
Expected: `Ran 17 tests` and `OK`.

The two skipped tests (`test_server_properties.py`'s `test_shipped_world`, whose CLI call Step 1 changed, and
`test_si_start_choice.py`'s `ArrivalRowTests`) and every other deploy check run in the whole deploy suite, from
`deploy/`:

Run: `(cd deploy && HDC_TEST_WORLD=/home/farral/Games/OfflineDAoC-archive/test-world/clean-classic-0.35.db HDC_CLASSIC_QUESTS=/home/farral/Games/DAoC/research/gos-epic-2026-10-09/classic-quests.json python3 -m unittest discover -s tests -t .)`
Expected: `Ran 610 tests` and `OK (skipped=11)` (600 at 56fbe98 plus this task's 10; about two minutes).

Run: `git diff --stat`
Expected: only these lines (the three new files are not tracked yet):

```
 .github/workflows/server-image.yml     |  2 +-
 deploy/.env.example                    |  5 +++++
 deploy/HANDOFF.md                      |  7 +++++--
 deploy/bin/server_properties.py        | 22 ++++++++++++++++++++++
 deploy/compose.yml                     |  1 +
 deploy/entrypoint.sh                   |  7 ++++---
 deploy/tests/test_server_properties.py | 23 +++++++++++++----------
 deploy/tests/test_si_start_choice.py   |  2 +-
 deploy/tests/test_workflows.py         |  4 ++--
 9 files changed, 54 insertions(+), 19 deletions(-)
```

- [ ] **Step 5: Commit.**

```bash
git add source/server/GameServer/scripts/hearthdaoc/RpTimerWaitScript.cs source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs deploy/tests/test_rp_timer_wait.py deploy/bin/server_properties.py deploy/entrypoint.sh deploy/compose.yml deploy/.env.example deploy/HANDOFF.md deploy/tests/test_server_properties.py deploy/tests/test_si_start_choice.py .github/workflows/server-image.yml deploy/tests/test_workflows.py
git commit -F - <<'EOF'
feat(rp-wait): the bot_rp_timer_wait switch, off in code and on in the deploy

The waits are off in code, like si_start_choice. HEARTHDAOC_BOT_RP_TIMER_WAIT (on or off, default on) goes from
.env through compose and the entrypoint to server_properties.py, which writes the property at every start and says
so when it changes it; a bad value stops the start. ./hdc update adds the new .env line to existing servers. CI
runs the wiring's test class.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

Expected: `12 files changed, 340 insertions(+), 19 deletions(-)`, with `create mode 100644` for
`deploy/tests/test_rp_timer_wait.py`, `source/server/GameServer/scripts/hearthdaoc/RpTimerWaitScript.cs` and
`source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs`.

---

### Task 8: The log lines and the timer and speed reads

**Files:**
- Modify: `source/server/GameServer/scripts/hearthdaoc/RpTimerWaitScript.cs` (`using System.Globalization;`; after the
  switch: the two TempProperty keys, the log prefix and the logger, the reads of the slot, the death record, the realm
  point timer, the time left and the best speed, the log words, `Seconds`, the four line builders and the three
  writers; Task 9 adds its members between `BestSpeed` and `CaseWord`)
- Modify: `source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs` (`using System.Numerics;` and 19 tests at the
  class's end: 12 `[Test]` methods and `SecondsRoundToTheNearestSecond`'s 7 rows)
- Modify: `deploy/tests/test_rp_timer_wait.py` (`ScriptWiringTests` with its first test)
- Test: `source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs`, `deploy/tests/test_rp_timer_wait.py`

**Spec:** 2.1 (time left, the upstream key), 2.2 (best speed), 7.2 (`WorthlessFor`, `BestSpeed(GameBot)`), 10.1
("Wiring": the literal key, `RP_WORTH_SECONDS` saved and restored, `GameLoopTime` set by reflection), 10.5 (the lines).

**Interfaces:**
- Consumes: Task 2's `RpTimerWait.WorthlessForMilliseconds(long lastDeathTick, long now, int rpWorthSeconds)` and
  `RpTimerWait.BestSpeed(short maxSpeed, short maxSpeedBase, double bestOwnSpeedValue)`; Task 1's `RpWaitSlot`,
  `RpDeathRecord`, `RpWaitMarker`, `RpWaitPhase`, `RpWaitCase`, `RpWaitReason`; Task 7's `RpTimerWaitScript` with its
  switch, and in the tests `SaveGlobals`/`RestoreGlobals` (the test double server; `RP_WORTH_SECONDS`, `GameLoopTime`
  and the switch saved and restored), `SetTime(long)` and `Bot()`; in `test_rp_timer_wait.py`, `source` and `SCRIPT_CS`.
  Upstream: `AutonomousBotRealmPointRewards.LastRealmPointDeathTickProperty` (`internal const string`, same assembly),
  `GameLoop.GameLoopTime`, `Properties.RP_WORTH_SECONDS`, `GlobalConstants.RealmToName(eRealm)`,
  `PropertyCollection.GetProperty<T>(key)` and `GetProperty<T>(key, default)`, `GameNPC.MiscSpells` and
  `InstantMiscSpells` (`List<Spell>`, may be null), `Spell.SpellType`, `IsPulsing`, `IsHarmful`, `Level`, `Value`,
  `GameLiving.MaxSpeed` and `MaxSpeedBase`, the bot's `Level`, `DOL.Logging.Logger` and `LoggerManager.Create`.
- Produces, in `public static class RpTimerWaitScript`:
  - `public const string WaitKey = "hearthdaoc.rp.wait"`, `public const string DeathKey = "hearthdaoc.rp.death"`,
    `public const string LogPrefix = "HEARTHDAOC_RP_WAIT"`, `private static readonly Logger Log` (Task 9's `OnDying`
    writes the died line with it);
  - `public static RpWaitSlot SlotOf(GameBot bot)`, `public static RpDeathRecord DeathRecordOf(GameBot bot)`,
    `public static long RealmPointDeathTick(GameBot bot)` (-1 when none), `public static long WorthlessFor(GameBot
    bot)`, `public static double BestSpeed(GameBot bot)`;
  - `public static string CaseWord(RpWaitCase value)`, `public static string ReasonWord(RpWaitReason value)`,
    `public static string Seconds(long milliseconds)`;
  - `public static string DiedLine(string name, long id, eRealm realm, eAutonomousObjectiveKind goal, eRealm
    killerRealm, bool worth, long sinceLastDeathMilliseconds, ushort region, int x, int y, int z)`,
    `public static string StartLine(string name, long id, eRealm realm, RpWaitMarker started, long timeLeft, long
    tripMilliseconds, long leaveInMilliseconds)`, `public static string SkipLine(string name, long id, eRealm realm,
    RpWaitCase hookCase, long timeLeft, RpWaitReason reason)`, `public static string LeaveLine(string name, long id,
    eRealm realm, RpWaitMarker waiting, long waitedMilliseconds, long timeLeft, long tripMilliseconds, RpWaitReason
    reason)`;
  - `public static void WriteStart(GameBot bot, RpWaitMarker started, long timeLeft, long tripMilliseconds, long
    leaveInMilliseconds)`, `public static void WriteSkip(GameBot bot, RpWaitCase hookCase, long timeLeft, RpWaitReason
    reason)`, `public static void WriteLeave(GameBot bot, RpWaitMarker waiting, long now, long timeLeft, long
    tripMilliseconds, RpWaitReason reason)` (Tasks 9 and 11 log through them);
  - and a private helper, `GroupField(RpWaitMarker)` (the start and leave lines' ` group=` field). In the tests,
    `using System.Numerics;` and the `Camelot` point, for Task 9 too.

- [ ] **Step 1: Write the failing tests.** The wiring's reads and its log lines, in `UT_RpTimerWaitScript`: the realm
point timer read through the upstream key, spelled out (the test project can't see ARPR's `internal` const), stored as
ARPR:90 writes it, a `long` (`GetProperty<long>` reads an `int` as no death at all); time left with the clock and
`rp_worth_seconds` set (Task 7's `[SetUp]` and `[TearDown]` save and restore both); the slot and the death record from
their own keys; whole seconds; a word for every case and reason; and each of the four lines compared whole. The
markers and the death record take a `Vector3`, so the file gets `using System.Numerics;`. All new tests go at the
class's end, after Task 7's test (each old text occurs once in the file as Task 7 left it):

```bash
python3 /tmp/hdc-edit.py source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs <<'EDIT'
<<<<<<< OLD
using System.Collections.Generic;
using System.Reflection;
=======
using System.Collections.Generic;
using System.Numerics;
using System.Reflection;
>>>>>>> NEW
<<<<<<< OLD
            "timer does, so they come back worth realm points"));
    }
}
=======
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
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs (2 block(s))`.

The source check that the timer is read through upstream's own const, not a copy of the string, goes before
`if __name__ == "__main__":`, with two blank lines before it, as every top-level class:

```bash
python3 /tmp/hdc-edit.py deploy/tests/test_rp_timer_wait.py <<'EDIT'
<<<<<<< OLD
        self.assertEqual(found, [("server", sp.RP_WAIT_DESCRIPTION, "false")])


if __name__ == "__main__":
=======
        self.assertEqual(found, [("server", sp.RP_WAIT_DESCRIPTION, "false")])


class ScriptWiringTests(unittest.TestCase):
    def test_the_timer_is_read_through_the_upstream_key(self):
        # The fork reads ARPR's internal const (same assembly); the unit tests use the literal key.
        self.assertIn("AutonomousBotRealmPointRewards.LastRealmPointDeathTickProperty", source(SCRIPT_CS))


if __name__ == "__main__":
>>>>>>> NEW
EDIT
```

Expected: `edited deploy/tests/test_rp_timer_wait.py (1 block(s))`.

- [ ] **Step 2: Run them and watch them fail.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWaitScript."`
Expected: the build fails (exit code 1) and no test runs. 22 errors, all `CS0117`, naming the 13 members the tests
call, each with the file's absolute path and the project at the end of the line:

```
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(110,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'RealmPointDeathTick'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(111,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'WorthlessFor'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(123,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'RealmPointDeathTick'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(124,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'WorthlessFor'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(126,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'WorthlessFor'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(137,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'WorthlessFor'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(144,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'SlotOf'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(145,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'DeathRecordOf'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(151,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'SlotOf'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(152,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'DeathRecordOf'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(153,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'WaitKey'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(154,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'DeathKey'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(166,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'Seconds'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(198,43): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'CaseWord'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(200,43): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'ReasonWord'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(207,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'DiedLine'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(217,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'DiedLine'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(231,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'StartLine'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(243,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'StartLine'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(251,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'SkipLine'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(263,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'LeaveLine'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(276,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'LeaveLine'
```

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_rp_timer_wait.py`
Expected: `FAIL: test_the_timer_is_read_through_the_upstream_key (tests.test_rp_timer_wait.ScriptWiringTests.test_the_timer_is_read_through_the_upstream_key)`
with `AssertionError: 'AutonomousBotRealmPointRewards.LastRealmPointDeathTickProperty' not found in 'using System;\nusing System.Numerics;\n...`
(the file as Task 7 left it), then `Ran 11 tests` and `FAILED (failures=1)`.

- [ ] **Step 3: Implement.** All three files are LF; the helper keeps LF. `RpTimerWaitScript.cs` gets
`using System.Globalization;` (the four lines are formatted in the invariant culture, as `ClassicBattlegrounds` formats
its numbers: under a culture such as `sv-SE` .NET writes a negative number with U+2212, not `-`), and after the switch,
in this order (Task 9's `NoteRelease`, `IsWaiting`, `WarbandWaits` and the handlers go between `BestSpeed`
and `CaseWord`):

- `SlotOf`, `DeathRecordOf` and `RealmPointDeathTick` are one TempProperty read each; the timer is read through ARPR's
  own `internal` const, with ARPR's own default, -1;
- `WorthlessFor` is Task 2's `WorthlessForMilliseconds` on the timer, the game clock and `rp_worth_seconds`;
- `BestSpeed` takes the largest `Value` among the bot's own speed songs it can sing (the song upkeep's pool and filter,
  BB:2177-2181), read from snapshots of both lists, which `GameBot.SortSpells` rebuilds in place on another thread
  (GB:1878-1890), skipping null entries, and hands it to Task 2's `BestSpeed`;
- the words and `Seconds` are 10.5's (`Seconds` rounds without adding 500 first, which would overflow just below
  `long.MaxValue`, the "never" of no speed);
- each line builder is one `string.Create(CultureInfo.InvariantCulture, ...)` over the `+`-joined interpolated parts
  (the compiler takes them as one interpolated string); the start and leave lines end with ` group=<session id>` for a
  marker with a session id;
- the writers log the line only when `Log.IsInfoEnabled`, with the bot's name, database id and realm; `WriteLeave`'s
  `waited` is `now - waiting.Started`.

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/scripts/hearthdaoc/RpTimerWaitScript.cs <<'EDIT'
<<<<<<< OLD
using System;
using System.Numerics;
=======
using System;
using System.Globalization;
using System.Numerics;
>>>>>>> NEW
<<<<<<< OLD
    public static bool BOT_RP_TIMER_WAIT;
}
=======
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
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/GameServer/scripts/hearthdaoc/RpTimerWaitScript.cs (2 block(s))`.

- [ ] **Step 4: Run them and watch them pass.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWaitScript."`
Expected: `Passed!  - Failed:     0, Passed:    20, Skipped:     0, Total:    20` (exit code 0: Task 7's test and this task's 19, the 13 names with
`SecondsRoundToTheNearestSecond`'s 7 rows; no warning names `RpTimerWaitScript.cs` or `UT_RpTimerWaitScript.cs`).

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_rp_timer_wait.py`
Expected: `Ran 11 tests` and `OK`.

Run: `dotnet build source/server/Tests/Tests.csproj --nologo -v q -clp:ErrorsOnly`
Expected: `Build succeeded.` and `0 Error(s)`; the warning total varies by a few between builds of the same tree
(634 or 639 while the plan was written), and no warning names a file this task changes.

CI's unit filter, as a cross-check (the full command of Global Constraints, with its prefix):

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_CommandPrivLevelOverrides|FullyQualifiedName~UT_SiStartChoice|FullyQualifiedName~UT_ClassicBattlegrounds|FullyQualifiedName~UT_DataQuestDependency|FullyQualifiedName~UT_DataQuestDeliveryItem|FullyQualifiedName~UT_DataQuestOffers|FullyQualifiedName~UT_QuestJournal|FullyQualifiedName~UT_DataQuestWhisper|FullyQualifiedName~UT_QuestNames|FullyQualifiedName~UT_ClassicQuestsExtra|FullyQualifiedName~UT_ClassicQuestsChoice|FullyQualifiedName~UT_LinkedCamps|FullyQualifiedName~UT_EpicChain|FullyQualifiedName~UT_QuestIndicatorProbe|FullyQualifiedName~UT_QuestIndicators|FullyQualifiedName~UT_IndicatorSentStore|FullyQualifiedName~UT_RpTimerWait|FullyQualifiedName~UT_RpTimerWaitScript"`
Expected: `Passed!  - Failed:     0, Passed:   604, Skipped:     0, Total:   604` (424 at 56fbe98, Tasks 1-6's 160, Task 7's 1 and this task's 19).

Run: `git diff --stat`
Expected: only these three files (git may shorten the paths to fit the terminal):

```
 deploy/tests/test_rp_timer_wait.py                               |   6 ++
 source/server/GameServer/scripts/hearthdaoc/RpTimerWaitScript.cs | 159 ++++++++++++++++++++++++++++++++++++++++
 source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs            | 183 +++++++++++++++++++++++++++++++++++++++++++++++
 3 files changed, 348 insertions(+)
```

- [ ] **Step 5: Commit.**

```bash
git add source/server/GameServer/scripts/hearthdaoc/RpTimerWaitScript.cs source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs deploy/tests/test_rp_timer_wait.py
git commit -F - <<'EOF'
feat(rp-wait): the wait log lines and the timer reads

The four log actions (died, start, skip, leave) as one line each, with whole seconds, so the owner can count kills
that paid nothing and how long bots sat out. The wiring reads the realm point timer through the reward code's own
key, the death record and the slot from their TempProperties, and a bot's best speed from its own speed songs.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

Expected: `3 files changed, 348 insertions(+)`.

---

### Task 9: The release note, the waiting check, the warband gate and the handlers, wired to the game

**Files:**
- Modify: `source/server/GameServer/scripts/hearthdaoc/RpTimerWaitScript.cs` (between `BestSpeed` and `CaseWord`:
  `NoteRelease`, `IsWaiting`, `WarbandWaits`, the `[ScriptLoadedEvent]` and `[ScriptUnloadedEvent]` registration, and
  the `Dying` and `MemberJoined` handlers; after this task the file is complete)
- Modify: `source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs` (4 tests and their helpers at the class's end; after
  this task the file is complete)
- Modify: `deploy/tests/test_rp_timer_wait.py` (`ScriptWiringTests`' other two tests)
- Test: `source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs`, `deploy/tests/test_rp_timer_wait.py`

**Spec:** 3.4 (the gate's reads and writes under the coordinator lock), 3.5 (hook 3), 3.7 (the `Dying` handler), 3.8
(the player-group handler), 7.2 (the marker first, then the switch; no `IsSafeArea`; swaps and lines), 10.2 (the
handlers' registration).

**Interfaces:**
- Consumes: Task 1's `RpWaitSlot` (`Current`, `TrySwap`, `Apply`), `RpWaitMarker`, `RpWaitChange` (`Before`, `Next`,
  `Action`, `Reason`, `Changes`), `RpWaitPhase`, `RpWaitCase`, `RpWaitAction`, `RpWarbandMember`, `RpWarbandGate`;
  Task 2's `RpTimerWait.IsBattlegroundRegion(ushort)` and `WorthlessForMilliseconds(long, long, int)`; Task 3's
  `RpTimerWait.Note(bool enabled, RpWaitMarker marker, int deathCount, bool alive, bool returning,
  eAutonomousObjectiveKind goal, ushort region, Vector3 position, string assignmentId, bool inGroup, bool
  forceCommitted, bool musterOrder)`, `Died(RpWaitMarker marker, int deathCount)` and `JoinedGroup(RpWaitMarker marker,
  int deathCount, bool leaderIsPlayer)`; Task 5's `WarbandWaits(bool enabled, eAutonomousObjectiveKind kind, bool
  forceCommitted, bool relicCarrier, ushort rendezvousRegion, Vector3 rendezvous, IReadOnlyList<RpWarbandMember>
  members)` and `WarbandMarks(RpWarbandGate gate, ushort rendezvousRegion, IReadOnlyList<RpWarbandMember> members,
  string sessionId, long now)`; Task 6's `RpTimerWait.IsWaiting(bool enabled, RpWaitMarker marker, int deathCount, long
  timeLeft, ushort region, Vector3 position, string assignmentId, bool playerLed, bool inGroup, Vector3?
  battlegroundArrival)`; Task 7's `RpTimerWaitScript.BOT_RP_TIMER_WAIT`, and in the tests `SaveGlobals`/`RestoreGlobals`
  (the test double server; the switch saved and restored) and `Bot()`; Task 8's `WaitKey`, `DeathKey`, `LogPrefix`,
  `Log`, `SlotOf`, `DeathRecordOf`, `RealmPointDeathTick`, `WorthlessFor`, `BestSpeed(GameBot)`, `DiedLine`,
  `WriteStart`, `WriteSkip` and `WriteLeave`, and in the tests `Camelot`; in `test_rp_timer_wait.py`, Task 7's
  `source`, `between`, `SCRIPT_CS`, `DECISIONS_CS` and `CONTROLLER_CS`, and Task 8's `ScriptWiringTests`. Upstream:
  `AutonomousRvrEventLayer.IsForceCommitted(string forceId, long nowTick)` and `GetRallyOrder(string forceId, eRealm
  realm, long nowTick)` (`RallyOrder`, null: none); `AutonomousBotGroupCoordinator.RendezvousFormationPoint(GameBot bot,
  string groupId, Vector3 center, bool tight)`; `GameRelic.IsPlayerCarryingRelic(GameLiving)`;
  `BattlegroundBrackets.ForRegion(ushort)` and `BotArrival(Bracket, eRealm)` (a `GameLocation`: `X`, `Y`, `Z`);
  `AutonomousObjectiveAssignments.KindFor(GameBot)`;
  `AutonomousBotRealmPointRewards.ResolveRootRewardOwner(GameLiving)`; `GameBot.PersistentRecord` (`DeathCount`,
  `ObjectiveAssignmentId`), `IsReturningAfterRelease`, `IsPlayerLedGroup`,
  `IsAutonomousWorldBot`, `IsTemporaryGroupHelper`; `GameEventMgr.AddHandler`/`RemoveHandler`,
  `GameLivingEvent.Dying`, `GroupEvent.MemberJoined`, `DyingEventArgs.Killer`, `MemberJoinedEventArgs.Member`,
  `Group.LivingLeader`; `PropertyCollection.TrySetProperty`, `SetProperty`, `GetProperty<string>`.
- Produces, in `public static class RpTimerWaitScript`:
  - `public static void NoteRelease(GameBot bot)` (hook 3, Task 10);
  - `public static bool IsWaiting(GameBot bot)` (hooks 5 and 6, Task 10);
  - `public static bool WarbandWaits(string sessionId, eAutonomousObjectiveKind objectiveKind, ushort rendezvousRegion,
    Vector3 rendezvous, GameBot[] members)` (hook 4, Task 10);
  - `[ScriptLoadedEvent] public static void OnScriptLoaded(DOLEvent e, object sender, EventArgs args)` and
    `[ScriptUnloadedEvent] public static void OnScriptUnloaded(DOLEvent e, object sender, EventArgs args)`, registering
    `private static void OnDying(DOLEvent e, object sender, EventArgs args)` (writes the death record that Task 11's
    `RpWaitFrontierTarget` reads through `DeathRecordOf`) and `private static void OnMemberJoined(DOLEvent e, object
    sender, EventArgs args)`.
  - In the tests: `WarbandSession`, `Rendezvous`, `Member(int deathCount)`, `SlotHolding(GameBot, RpWaitMarker)` and
    `ReleasedInCamelot(int deathCount)`.

- [ ] **Step 1: Write the failing tests.** The entry points' early returns, in `UT_RpTimerWaitScript`: each reads the
bot's marker first and leaves at once without one, so a gamebot made without its constructor (only its TempProperties
and a `PersistentRecord` are real; a read of anything else that needs the constructor, its speed for one, throws)
passes through each of them with no slot made and nothing written. `IsWaiting` with no marker; `NoteRelease` for a bot
with an RvR goal that has no marker and no release flag (no slot is made); the warband gate with no member's marker,
then with a member released for its death now in a Group PvE party and with the switch off (no write: the marker stays
the same reference); and the gate with every marker Left or for an older death. A member's death count needs a
`PersistentRecord`, whose setter is private: `Member` sets it by reflection. All new members go at the class's end,
after Task 8's last test (the old text occurs once in the file as Task 8 left it):

```bash
python3 /tmp/hdc-edit.py source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs <<'EDIT'
<<<<<<< OLD
                       "worthIn=175 trip=- reason=off"));
    }
}
=======
                       "worthIn=175 trip=- reason=off"));
    }

    // The entry points the hooks call read the bot's marker first and leave at once without one (7.2): every
    // gamebot passes hook 3 on every controller turn and hooks 5 and 6 on every recruiting pass and threat scan, and
    // most never wait. These gamebots have only their TempProperties and a PersistentRecord: a read of anything else
    // that needs the constructor (their speed, for one) throws.

    private const string WarbandSession = "albion-7f3a-007";
    // The warband's rendezvous by the border keep, in Albion's frontier (region 1).
    private static readonly Vector3 Rendezvous = new(29_500, 31_000, 4_310);

    // A gamebot with an RvR goal at the given death count (PersistentRecord has a private setter).
    private static GameBot Member(int deathCount)
    {
        GameBot bot = Bot();
        typeof(GameBot).GetProperty(nameof(GameBot.PersistentRecord))!.SetValue(bot, new OfflineWorldBotRecord
        {
            DeathCount = deathCount,
            ObjectiveKind = "RvR",
            ObjectiveAssignmentId = "albion-40-12-RvR",
        });
        return bot;
    }

    // The bot's slot, holding the marker, as hook 3 makes it at a first release.
    private static RpWaitSlot SlotHolding(GameBot bot, RpWaitMarker marker)
    {
        var slot = new RpWaitSlot();
        Assert.That(slot.TrySwap(null, marker), Is.True);
        bot.TempProperties.SetProperty("hearthdaoc.rp.wait", slot);
        return slot;
    }

    // Released in Camelot for the given death: a warband member before its first pass of the gate.
    private static RpWaitMarker ReleasedInCamelot(int deathCount) =>
        new(deathCount, RpWaitPhase.Released, RpWaitCase.None, 10, Camelot, 10, Camelot, "albion-40-12-RvR", null, null,
            0);

    [Test]
    public void ABotWithNoMarkerIsNotWaiting()
    {
        // Hooks 5 and 6 with the switch on: no slot, so the bot is recruited and charges as upstream.
        RpTimerWaitScript.BOT_RP_TIMER_WAIT = true;
        Assert.That(RpTimerWaitScript.IsWaiting(Bot()), Is.False);
        Assert.That(RpTimerWaitScript.IsWaiting(Member(3)), Is.False);
    }

    [Test]
    public void NoteReleaseLeavesABotWithNoMarkerThatIsNotReturningAlone()
    {
        // Hook 3 with the switch on, for a bot with an RvR goal that was not released (alive in the field, or
        // resurrected where it fell): no marker to write, so no slot either. A slot is made only for a first marker.
        RpTimerWaitScript.BOT_RP_TIMER_WAIT = true;
        GameBot bot = Member(3);
        Assert.That(bot.IsReturningAfterRelease, Is.False);
        RpTimerWaitScript.NoteRelease(bot);
        Assert.That(RpTimerWaitScript.SlotOf(bot), Is.Null);
    }

    [Test]
    public void TheWarbandGateWritesNothingWithoutMarkersForAPveSessionOrWithTheSwitchOff()
    {
        // Hook 4 on a regroup pass, the switch on: no member has a marker, so the warband goes at once and the gate
        // makes no slot.
        RpTimerWaitScript.BOT_RP_TIMER_WAIT = true;
        GameBot first = Member(3), second = Member(5);
        Assert.That(RpTimerWaitScript.WarbandWaits(WarbandSession, eAutonomousObjectiveKind.RvR, 1, Rendezvous,
            [first, second]), Is.False);
        Assert.That(RpTimerWaitScript.SlotOf(first), Is.Null);
        Assert.That(RpTimerWaitScript.SlotOf(second), Is.Null);

        // A member released for its death now: a Group PvE party goes at once (a monster kill restarts the timer too),
        // and so does an RvR warband with the switch off. The marker stays as it was (spec 3.4, section 6).
        RpWaitSlot slot = SlotHolding(first, ReleasedInCamelot(3));
        RpWaitMarker released = slot.Current;
        Assert.That(RpTimerWaitScript.WarbandWaits(WarbandSession, eAutonomousObjectiveKind.GroupPve, 1, Rendezvous,
            [first, second]), Is.False);
        Assert.That(slot.Current, Is.SameAs(released));
        RpTimerWaitScript.BOT_RP_TIMER_WAIT = false;
        Assert.That(RpTimerWaitScript.WarbandWaits(WarbandSession, eAutonomousObjectiveKind.RvR, 1, Rendezvous,
            [first, second]), Is.False);
        Assert.That(slot.Current, Is.SameAs(released));
        Assert.That(RpTimerWaitScript.SlotOf(second), Is.Null);
    }

    [Test]
    public void TheWarbandGateGoesAtOnceWhenEveryMarkerIsLeft()
    {
        // The switch on, an RvR warband, and no member released for its death now: the first member's warband wait is
        // over, the second's release was latched when the gate opened, and the third still has its last death's
        // Released marker, which the Dying handler is about to latch. A slot lasts the whole run, so this is the
        // gate's commonest pass: it goes at once and writes nothing.
        RpTimerWaitScript.BOT_RP_TIMER_WAIT = true;
        GameBot first = Member(3), second = Member(5), third = Member(4);
        RpWaitSlot[] slots =
        [
            SlotHolding(first, new RpWaitMarker(3, RpWaitPhase.Left, RpWaitCase.Warband, 10, Camelot, 1,
                new Vector3(29_640, 31_220, 4_310), "albion-40-12-RvR", WarbandSession, null, 1_030_000)),
            SlotHolding(second, ReleasedInCamelot(5) with { Phase = RpWaitPhase.Left }),
            SlotHolding(third, ReleasedInCamelot(3)),
        ];
        RpWaitMarker[] before = Array.ConvertAll(slots, slot => slot.Current);
        Assert.That(RpTimerWaitScript.WarbandWaits(WarbandSession, eAutonomousObjectiveKind.RvR, 1, Rendezvous,
            [first, second, third]), Is.False);
        for (int i = 0; i < slots.Length; i++)
            Assert.That(slots[i].Current, Is.SameAs(before[i]), $"member {i}");
    }
}
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs (1 block(s))`.

The source checks that the handlers are registered at script load and removed at unload, and that no wait code calls
`IsSafeArea` (an allocation hot spot, FT:142-143), go in `ScriptWiringTests` after its first test:

```bash
python3 /tmp/hdc-edit.py deploy/tests/test_rp_timer_wait.py <<'EDIT'
<<<<<<< OLD
        self.assertIn("AutonomousBotRealmPointRewards.LastRealmPointDeathTickProperty", source(SCRIPT_CS))


if __name__ == "__main__":
=======
        self.assertIn("AutonomousBotRealmPointRewards.LastRealmPointDeathTickProperty", source(SCRIPT_CS))

    def test_the_script_registers_the_death_and_group_handlers(self):
        text = source(SCRIPT_CS)
        loaded = between(text, "public static void OnScriptLoaded(", "\n    }\n")
        self.assertIn("GameEventMgr.AddHandler(GameLivingEvent.Dying, OnDying);", loaded)
        self.assertIn("GameEventMgr.AddHandler(GroupEvent.MemberJoined, OnMemberJoined);", loaded)
        unloaded = between(text, "public static void OnScriptUnloaded(", "\n    }\n")
        self.assertIn("GameEventMgr.RemoveHandler(GameLivingEvent.Dying, OnDying);", unloaded)
        self.assertIn("GameEventMgr.RemoveHandler(GroupEvent.MemberJoined, OnMemberJoined);", unloaded)
        self.assertIn("[ScriptLoadedEvent]", text)

    def test_no_wait_code_calls_is_safe_area(self):
        for path in (DECISIONS_CS, SCRIPT_CS, CONTROLLER_CS):
            if os.path.exists(path):
                self.assertNotIn("IsSafeArea(", source(path), path)


if __name__ == "__main__":
>>>>>>> NEW
EDIT
```

Expected: `edited deploy/tests/test_rp_timer_wait.py (1 block(s))`.

- [ ] **Step 2: Run them and watch them fail.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWaitScript."`
Expected: the build fails (exit code 1) and no test runs. 7 errors, all `CS0117`, naming the 3 members the tests call,
each with the file's absolute path and the project at the end of the line:

```
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(323,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'IsWaiting'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(324,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'IsWaiting'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(335,27): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'NoteRelease'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(346,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'WarbandWaits'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(355,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'WarbandWaits'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(359,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'WarbandWaits'
source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs(382,39): error CS0117: 'RpTimerWaitScript' does not contain a definition for 'WarbandWaits'
```

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_rp_timer_wait.py`
Expected: `ERROR: test_the_script_registers_the_death_and_group_handlers (tests.test_rp_timer_wait.ScriptWiringTests.test_the_script_registers_the_death_and_group_handlers)`
with `ValueError: substring not found` from `between` (the file has no `OnScriptLoaded` yet), then `Ran 13 tests` and
`FAILED (errors=1)`. `test_no_wait_code_calls_is_safe_area` passes already: no wait code calls `IsSafeArea`.

- [ ] **Step 3: Implement.** `RpTimerWaitScript.cs` is LF; the helper keeps LF. Each member is under its rule comment
(`WarbandWaits`' also says why a gate opened with no holder logs `trip=-`). Between `BestSpeed` and `CaseWord`, in
this order:

- `NoteRelease` (hook 3) reads the slot's marker and the release flag and leaves at once with neither, then leaves for a
  bot with no `PersistentRecord`. Only for a marker Waiting for this death, with the switch on and the same assignment
  id and region, it asks the event layer: a frontier wait whether its force is committed, a siege or warband wait
  whether its force has a muster order; the force is the warband's session id, else the one ExecuteRvr recorded
  (`RvrEventForce`), else `rvr-<id>`. It asks Task 3's `Note`, makes the slot only to write a first marker, swaps against
  the marker it read, and after a successful swap writes a leave line with no trip for a `Leave`.
- `IsWaiting` (hooks 5 and 6) reads the marker, then the switch, then the `PersistentRecord`, and hands Task 6's
  `IsWaiting` the bot's death count, time left, region, position, assignment id, player-led flag and group, with its
  realm's battleground arrival point only for a Released marker in a battleground region.
- `WarbandWaits` (hook 4, under the coordinator lock) reads each member's slot and marker once and goes at once, writing
  nothing, unless some member is Released or Waiting for its death now (a slot lasts the whole run, so this is the
  common pass); then with the switch off or a session that is not RvR; then with a committed force (one
  `IsForceCommitted` read). It builds each member's view (the formation slot only for a member the gate can turn
  Waiting), asks Task 5's `WarbandWaits` and `WarbandMarks`, swaps each change against the marker read, and logs only
  after a successful swap: `start` (its own time left, the march, the holder's time left less the march), `leave` (the
  march, or `-` when no member holds the gate) and `skip` (case warband).
- `OnScriptLoaded` and `OnScriptUnloaded` add and remove the two handlers, as `LinkedCamps.cs:59-61` does.
- `OnDying` (any living's death) leaves at once for anything but a persistent gamebot. With the switch on or off it
  writes the death record (with the timer as ARPR:90 has just written it) and, for a kill by another realm
  (`RVR_BOT_KILLED`'s filter), the died line, whose `worth` is what ARPR:86 read: the previous record's timer value. Then
  `Apply` (the handler has no next turn, so it retries a lost swap) ends a running wait, with its leave line.
- `OnMemberJoined` ends a wait or a release for this death when the group's leader is a player, with `Apply`, and a
  leave line for a wait.
- Both handlers catch and log any exception (`Log.Error`): a fork handler must never break a death or a group join.

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/scripts/hearthdaoc/RpTimerWaitScript.cs <<'EDIT'
<<<<<<< OLD
            return best;
        }
    }

    // 10.5: none, battleground, frontier, siege, warband.
=======
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
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/GameServer/scripts/hearthdaoc/RpTimerWaitScript.cs (1 block(s))`.

- [ ] **Step 4: Run them and watch them pass.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_RpTimerWaitScript."`
Expected: `Passed!  - Failed:     0, Passed:    24, Skipped:     0, Total:    24` (exit code 0: Task 7's 1, Task 8's 19
and this task's 4; no warning names `RpTimerWaitScript.cs` or `UT_RpTimerWaitScript.cs`).

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_rp_timer_wait.py`
Expected: `Ran 13 tests` and `OK`.

Run: `dotnet build source/server/Tests/Tests.csproj --nologo -v q -clp:ErrorsOnly`
Expected: `Build succeeded.` and `0 Error(s)`; the warning total varies by a few between builds of the same tree
(634 or 639 while the plan was written), and no warning names a file this task changes.

CI's unit filter (the full command of Global Constraints, with its prefix):

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_CommandPrivLevelOverrides|FullyQualifiedName~UT_SiStartChoice|FullyQualifiedName~UT_ClassicBattlegrounds|FullyQualifiedName~UT_DataQuestDependency|FullyQualifiedName~UT_DataQuestDeliveryItem|FullyQualifiedName~UT_DataQuestOffers|FullyQualifiedName~UT_QuestJournal|FullyQualifiedName~UT_DataQuestWhisper|FullyQualifiedName~UT_QuestNames|FullyQualifiedName~UT_ClassicQuestsExtra|FullyQualifiedName~UT_ClassicQuestsChoice|FullyQualifiedName~UT_LinkedCamps|FullyQualifiedName~UT_EpicChain|FullyQualifiedName~UT_QuestIndicatorProbe|FullyQualifiedName~UT_QuestIndicators|FullyQualifiedName~UT_IndicatorSentStore|FullyQualifiedName~UT_RpTimerWait|FullyQualifiedName~UT_RpTimerWaitScript"`
Expected: `Passed!  - Failed:     0, Passed:   608, Skipped:     0, Total:   608` (424 at 56fbe98, Tasks 1-6's 160, Task 7's 1,
Task 8's 19 and this task's 4).

The whole deploy suite, as a cross-check (run after the unit tests, not at the same time), from `deploy/`:

Run: `(cd deploy && HDC_TEST_WORLD=/home/farral/Games/OfflineDAoC-archive/test-world/clean-classic-0.35.db HDC_CLASSIC_QUESTS=/home/farral/Games/DAoC/research/gos-epic-2026-10-09/classic-quests.json python3 -m unittest discover -s tests -t .)`
Expected: `Ran 613 tests` and `OK (skipped=11)` (Task 8's 611 and this task's 2; about two minutes).

Run: `git diff --stat`
Expected: only these three files (git may shorten the paths to fit the terminal, as here):

```
 deploy/tests/test_rp_timer_wait.py                 |  15 ++
 .../scripts/hearthdaoc/RpTimerWaitScript.cs        | 249 +++++++++++++++++++++
 .../server/Tests/UnitTests/UT_RpTimerWaitScript.cs | 106 +++++++++
 3 files changed, 370 insertions(+)
```

- [ ] **Step 5: Commit.**

```bash
git add source/server/GameServer/scripts/hearthdaoc/RpTimerWaitScript.cs source/server/Tests/UnitTests/UT_RpTimerWaitScript.cs deploy/tests/test_rp_timer_wait.py
git commit -F - <<'EOF'
feat(rp-wait): wire the release note, the waiting check, the warband gate and the handlers

Each entry point reads the bot's marker first and leaves at once for a bot with none, then reads the switch. The
release note asks the event layer only for a waiting bot; the warband gate does nothing for a warband with no member
released for its current death, reads one committed-force flag per pass under the coordinator lock and logs a line
only after a successful swap. A death handler records each gamebot's death and ends a running wait; a group handler
ends a wait when a player invites the bot.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

Expected: `3 files changed, 370 insertions(+)`.

---

### Task 10: Hooks 3-6: the release note, the warband gate, recruiting and the threat scan

**Files:**
- Modify: `source/server/GameServer/bots/autonomous/AutonomousWorldBotController.cs` (hook 3, in `Tick` after
  `ObserveDeaths(bot);`; LF, no BOM)
- Modify: `source/server/GameServer/bots/autonomous/AutonomousBotGroupCoordinator.cs` (hook 5, in `TryFormGroups`'
  recruiting filter; hook 4, in `UpdateSession`'s regroup completion; LF, no BOM)
- Modify: `source/server/GameServer/bots/autonomous/AutonomousWorldBotController.FrontierThreat.cs` (hook 6, in
  `TryEngageFrontierThreat`'s `nearby` chain; LF, no BOM)
- Modify: `deploy/tests/test_rp_timer_wait.py` (`UpstreamHookTests` and `UpstreamFactTests`, before the main guard)
- Test: `deploy/tests/test_rp_timer_wait.py`

**Spec:** 3.4 (hook 4: the warband leaves together), 3.5 (hook 3: the release note, before the hand-over clears the
flag), 3.6 (hook 5: no recruiting of waiting bots), section 4 (hook 6: a waiting bot fights back but charges nothing it
only sees), 7.4 (the six upstream lines), 10.2 (the source checks).

**Interfaces:**
- Consumes: Task 9's `public static void RpTimerWaitScript.NoteRelease(GameBot bot)`, `public static bool
  RpTimerWaitScript.IsWaiting(GameBot bot)` and `public static bool RpTimerWaitScript.WarbandWaits(string sessionId,
  eAutonomousObjectiveKind objectiveKind, ushort rendezvousRegion, Vector3 rendezvous, GameBot[] members)` (namespace
  `DOL.GS.HearthDAoC`, so `HearthDAoC.RpTimerWaitScript` from upstream code in `DOL.GS`). Upstream: `private static bool
  FiringOnRealm(GameBot bot, GameLiving target)` (FT:113); the coordinator's private `Session` (`Id` `string`,
  `ObjectiveKind` `eAutonomousObjectiveKind`, `RendezvousRegion` `ushort`, `Rendezvous` `Vector3`) and `UpdateSession`'s
  `GameBot[] members`. In `test_rp_timer_wait.py`, Task 7's `source`, `between`, `marked`, `WBC`, `BG`, `FT`, `GC` and
  `ARPR`.
- Produces: four upstream lines, each under its own `// HearthDAoC:` comment line (8 inserted lines, no deletions):
  - hook 3, WBC `Tick`: `HearthDAoC.RpTimerWaitScript.NoteRelease(bot);`
  - hook 4, GC `UpdateSession`: `!HearthDAoC.RpTimerWaitScript.WarbandWaits(session.Id, session.ObjectiveKind,
    session.RendezvousRegion, session.Rendezvous, members) &&`, between `session.LeaderReadyForAssembly &&` and
    `session.Recovery.TryComplete(...)`
  - hook 5, GC `TryFormGroups`: `!HearthDAoC.RpTimerWaitScript.IsWaiting(bot) &&`
  - hook 6, FT `TryEngageFrontierThreat`: `.Where(target => !HearthDAoC.RpTimerWaitScript.IsWaiting(bot) ||
    FiringOnRealm(bot, target))`
  - In the source checks: `UpstreamHookTests` (4 tests) and `UpstreamFactTests` (3 tests).

- [ ] **Step 1: Write the failing tests.** The source checks of 10.2 for hooks 3-6 and the upstream facts the waits
mirror. `UpstreamHookTests` pins each hook's place with index comparisons inside its method, and `marked` (Task 7)
checks that the call occurs once with a `// HearthDAoC:` comment on the line above it: the note after the companion
return and `ObserveDeaths(bot);`, before the braceless `if (!bot.IsPlayerLedGroup)`, which must still be followed
directly by `bot.HandOverReleaseReturnToGroup();`; the gate in the same condition as `session.Recovery.TryComplete(`,
before it; the recruiting check inside the `available` filter; the threat filter inside the `nearby` chain, after the
radius filter and before `.OrderBy(`. `UpstreamFactTests` pins the realm point timer as ARPR computes it, the roam
anchor's 0.6 and 900 and the scan's 5,000 behind `FirstContactPoint`, the `RvrEventForce` key and
`RendezvousFormationPoint`'s signature: a sync from upstream that changes one fails here. Both classes go after
`ScriptWiringTests`, before the main guard (the old text occurs once in the file as Task 9 left it):

```bash
python3 /tmp/hdc-edit.py deploy/tests/test_rp_timer_wait.py <<'EDIT'
<<<<<<< OLD
                self.assertNotIn("IsSafeArea(", source(path), path)


if __name__ == "__main__":
=======
                self.assertNotIn("IsSafeArea(", source(path), path)


class UpstreamHookTests(unittest.TestCase):
    def test_the_release_note_comes_after_observe_deaths_and_before_the_hand_over(self):
        tick = between(source(WBC), "public bool Tick(BotBrain brain)", "if (!bot.IsAlive || bot.IsReturningAfterRelease)")
        call = "HearthDAoC.RpTimerWaitScript.NoteRelease(bot);"
        marked(self, tick, call)
        self.assertLess(tick.index("bot.IsTemporaryGroupHelper || bot.IsPlayerLedGroup)\n                return false;"),
                        tick.index(call))
        self.assertLess(tick.index("ObserveDeaths(bot);"), tick.index(call))
        self.assertLess(tick.index(call), tick.index("if (!bot.IsPlayerLedGroup)"))
        self.assertIn("if (!bot.IsPlayerLedGroup)\n                    bot.HandOverReleaseReturnToGroup();", tick)

    def test_the_warband_gate_is_in_the_regroup_completion_before_try_complete(self):
        text = source(GC)
        condition = between(text, "if (session.LeaderReadyForAssembly &&\n", "\n            {")
        call = ("!HearthDAoC.RpTimerWaitScript.WarbandWaits(session.Id, session.ObjectiveKind, session.RendezvousRegion, "
                "session.Rendezvous, members) &&")
        marked(self, condition, call)
        self.assertLess(condition.index(call), condition.index("session.Recovery.TryComplete("))

    def test_recruiting_skips_waiting_bots(self):
        available = between(source(GC), "GameBot[] available = activeRoster", ".ToArray();")
        marked(self, available, "!HearthDAoC.RpTimerWaitScript.IsWaiting(bot) &&")
        self.assertLess(available.index("IsWaiting(bot)"), available.index(".OrderBy("))

    def test_the_threat_scan_filter_is_inside_the_nearby_chain(self):
        nearby = between(source(FT), "GameLiving[] nearby = ", ".ToArray();")
        call = ".Where(target => !HearthDAoC.RpTimerWaitScript.IsWaiting(bot) || FiringOnRealm(bot, target))"
        marked(self, nearby, call)
        self.assertLess(nearby.index("<= TargetSearchRadius)"), nearby.index(call))
        self.assertLess(nearby.index(call), nearby.index(".OrderBy("))


class UpstreamFactTests(unittest.TestCase):
    """What the waits mirror from upstream code: a sync that changes one fails here."""

    def test_the_realm_point_timer_is_as_the_waits_mirror_it(self):
        text = source(ARPR)
        self.assertIn('internal const string LastRealmPointDeathTickProperty = "autonomous.rvr.last.realm.point.death.tick";', text)
        self.assertIn("long worthInterval = Math.Max(0, Properties.RP_WORTH_SECONDS) * 1000L;", text)
        self.assertIn("bool isWorthRealmPoints = previousDeath < 0 || now - previousDeath >= worthInterval;", text)

    def test_the_first_contact_point_is_from_upstreams_roam_and_scan(self):
        roam = between(source(BG), "private bool RoamBattleground(", "IssueVariedRvrPath(")
        self.assertIn("central != null ? new(central.X, central.Y, central.Z) : new(entry.X, entry.Y, entry.Z), 0.6f))", roam)
        self.assertIn("anchor = nav.GetRandomPoint(zone, anchor, 900, nav.DefaultFilters) ?? anchor;", roam)
        self.assertIn("private const int TargetSearchRadius = 5000;", source(WBC))

    def test_the_force_key_and_the_formation_point_are_upstreams(self):
        self.assertIn('bot.TempProperties.SetProperty("RvrEventForce", forceId);', source(WBC))
        self.assertIn("public static Vector3 RendezvousFormationPoint(GameBot bot, string groupId, Vector3 center, bool tight)",
                      source(GC))


if __name__ == "__main__":
>>>>>>> NEW
EDIT
```

Expected: `edited deploy/tests/test_rp_timer_wait.py (1 block(s))`.

- [ ] **Step 2: Run them and watch them fail.**

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_rp_timer_wait.py`
Expected: the progress line `................FFFF`, then four failures, each from `marked`'s count (the call is not in
the upstream file yet):

```
FAIL: test_recruiting_skips_waiting_bots (tests.test_rp_timer_wait.UpstreamHookTests.test_recruiting_skips_waiting_bots)
AssertionError: 0 != 1 : !HearthDAoC.RpTimerWaitScript.IsWaiting(bot) &&
FAIL: test_the_release_note_comes_after_observe_deaths_and_before_the_hand_over (tests.test_rp_timer_wait.UpstreamHookTests.test_the_release_note_comes_after_observe_deaths_and_before_the_hand_over)
AssertionError: 0 != 1 : HearthDAoC.RpTimerWaitScript.NoteRelease(bot);
FAIL: test_the_threat_scan_filter_is_inside_the_nearby_chain (tests.test_rp_timer_wait.UpstreamHookTests.test_the_threat_scan_filter_is_inside_the_nearby_chain)
AssertionError: 0 != 1 : .Where(target => !HearthDAoC.RpTimerWaitScript.IsWaiting(bot) || FiringOnRealm(bot, target))
FAIL: test_the_warband_gate_is_in_the_regroup_completion_before_try_complete (tests.test_rp_timer_wait.UpstreamHookTests.test_the_warband_gate_is_in_the_regroup_completion_before_try_complete)
AssertionError: 0 != 1 : !HearthDAoC.RpTimerWaitScript.WarbandWaits(session.Id, session.ObjectiveKind, session.RendezvousRegion, session.Rendezvous, members) &&
```

then `Ran 20 tests` and `FAILED (failures=4)`. The three `UpstreamFactTests` pass already: they pin upstream as it is.

- [ ] **Step 3: Implement.** The three upstream files are LF with no BOM; the helper keeps both and adds only the
lines below (each OLD text occurs once in its file at 56fbe98 and after Tasks 1-9, which touched no upstream file).

Hook 3, in `Tick`, after `ObserveDeaths(bot);` and before the braceless `if (!bot.IsPlayerLedGroup)` (never between
that `if` and its `bot.HandOverReleaseReturnToGroup();`): the last place where a release can still be read, after the
companion and player-led return (WBC:226-227), so those bots never get a marker.

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/bots/autonomous/AutonomousWorldBotController.cs <<'EDIT'
<<<<<<< OLD
                ObserveDeaths(bot);

                // Every autonomous return uses the same navmesh controller,
=======
                ObserveDeaths(bot);
                // HearthDAoC: note a release (not a resurrection) before the hand-over clears it.
                HearthDAoC.RpTimerWaitScript.NoteRelease(bot);

                // Every autonomous return uses the same navmesh controller,
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/GameServer/bots/autonomous/AutonomousWorldBotController.cs (1 block(s))`.

Hooks 5 and 4 in one run. Hook 5 goes into `TryFormGroups`' recruiting filter after `!AutonomousRealmRaid.IsReserved(bot)
&&` (its continuation lines are indented 26 spaces, as the file has them); hook 4 into `UpdateSession`'s regroup
completion, between `session.LeaderReadyForAssembly &&` and `session.Recovery.TryComplete(...)`, so the completion waits
while the gate holds (the coordinator lock is already held there, GC:212):

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/bots/autonomous/AutonomousBotGroupCoordinator.cs <<'EDIT'
<<<<<<< OLD
                          !AutonomousRealmRaid.IsReserved(bot) &&
                          // siege recruits are merged into full parties by FormSiegeParties, not random warbands
=======
                          !AutonomousRealmRaid.IsReserved(bot) &&
                          // HearthDAoC: a bot waiting out the realm point timer joins no new roaming warband.
                          !HearthDAoC.RpTimerWaitScript.IsWaiting(bot) &&
                          // siege recruits are merged into full parties by FormSiegeParties, not random warbands
>>>>>>> NEW
<<<<<<< OLD
            if (session.LeaderReadyForAssembly &&
                session.Recovery.TryComplete(RecoveryMembers(session, members, true), GameLoop.GameLoopTime))
=======
            if (session.LeaderReadyForAssembly &&
                // HearthDAoC: the warband leaves together once its member with the most time left can make the march.
                !HearthDAoC.RpTimerWaitScript.WarbandWaits(session.Id, session.ObjectiveKind, session.RendezvousRegion, session.Rendezvous, members) &&
                session.Recovery.TryComplete(RecoveryMembers(session, members, true), GameLoop.GameLoopTime))
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/GameServer/bots/autonomous/AutonomousBotGroupCoordinator.cs (2 block(s))`.

Hook 6, in `TryEngageFrontierThreat`'s `nearby` chain, after the radius filter: a waiting bot keeps only enemies firing
on it or on a realm-mate within 1,000 (`FiringOnRealm`), so it fights back but charges nothing it only sees; a bot that
is not waiting keeps every target, as before.

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/bots/autonomous/AutonomousWorldBotController.FrontierThreat.cs <<'EDIT'
<<<<<<< OLD
            .Where(target => bot.GetDistanceTo(target) <= TargetSearchRadius)
            .Where(target => defending || !BotSiegeRuntime.Assigned(bot) || bot.IsWithinRadius(target, 450) && target is not GameSiegeWeapon)
=======
            .Where(target => bot.GetDistanceTo(target) <= TargetSearchRadius)
            // HearthDAoC: a bot waiting out the realm point timer answers only enemies attacking it or a realm-mate near it.
            .Where(target => !HearthDAoC.RpTimerWaitScript.IsWaiting(bot) || FiringOnRealm(bot, target))
            .Where(target => defending || !BotSiegeRuntime.Assigned(bot) || bot.IsWithinRadius(target, 450) && target is not GameSiegeWeapon)
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/GameServer/bots/autonomous/AutonomousWorldBotController.FrontierThreat.cs (1 block(s))`.

- [ ] **Step 4: Run them and watch them pass.**

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_rp_timer_wait.py`
Expected: `Ran 20 tests` and `OK`.

Run: `dotnet build source/server/Tests/Tests.csproj --nologo -v q -clp:ErrorsOnly`
Expected: `Build succeeded.` and `0 Error(s)`; the warning total varies by a few between builds of the same tree
(634 or 639 while the plan was written), and no warning names a file this task changes.

CI's unit filter (the full command of Global Constraints, with its prefix); this task adds no unit test, so the count
is Task 9's:

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_CommandPrivLevelOverrides|FullyQualifiedName~UT_SiStartChoice|FullyQualifiedName~UT_ClassicBattlegrounds|FullyQualifiedName~UT_DataQuestDependency|FullyQualifiedName~UT_DataQuestDeliveryItem|FullyQualifiedName~UT_DataQuestOffers|FullyQualifiedName~UT_QuestJournal|FullyQualifiedName~UT_DataQuestWhisper|FullyQualifiedName~UT_QuestNames|FullyQualifiedName~UT_ClassicQuestsExtra|FullyQualifiedName~UT_ClassicQuestsChoice|FullyQualifiedName~UT_LinkedCamps|FullyQualifiedName~UT_EpicChain|FullyQualifiedName~UT_QuestIndicatorProbe|FullyQualifiedName~UT_QuestIndicators|FullyQualifiedName~UT_IndicatorSentStore|FullyQualifiedName~UT_RpTimerWait|FullyQualifiedName~UT_RpTimerWaitScript"`
Expected: `Passed!  - Failed:     0, Passed:   608, Skipped:     0, Total:   608` (424 at 56fbe98, Tasks 1-6's 160, Task 7's 1,
Task 8's 19 and Task 9's 4).

The whole deploy suite, as a cross-check (run after the unit tests, not at the same time), from `deploy/`:

Run: `(cd deploy && HDC_TEST_WORLD=/home/farral/Games/OfflineDAoC-archive/test-world/clean-classic-0.35.db HDC_CLASSIC_QUESTS=/home/farral/Games/DAoC/research/gos-epic-2026-10-09/classic-quests.json python3 -m unittest discover -s tests -t .)`
Expected: `Ran 620 tests` and `OK (skipped=11)` (Task 9's 613 and this task's 7; about two minutes).

Run: `git diff --stat`
Expected: only these four files, the three upstream ones with 8 insertions and no deletions (WBC 2, GC 4, FT 2; git
may shorten the paths to fit the terminal, as here):

```
 deploy/tests/test_rp_timer_wait.py                 | 53 ++++++++++++++++++++++
 .../autonomous/AutonomousBotGroupCoordinator.cs    |  4 ++
 .../AutonomousWorldBotController.FrontierThreat.cs |  2 +
 .../autonomous/AutonomousWorldBotController.cs     |  2 +
 4 files changed, 61 insertions(+)
```

- [ ] **Step 5: Commit.**

```bash
git add source/server/GameServer/bots/autonomous/AutonomousWorldBotController.cs source/server/GameServer/bots/autonomous/AutonomousBotGroupCoordinator.cs source/server/GameServer/bots/autonomous/AutonomousWorldBotController.FrontierThreat.cs deploy/tests/test_rp_timer_wait.py
git commit -F - <<'EOF'
feat(rp-wait): hooks for the release note, the warband gate, recruiting and the threat scan

Four marked upstream lines: Tick notes a release before the hand-over clears it; the regroup completes only once the
warband gate opens; recruiting skips waiting bots; and a waiting bot's threat scan keeps only enemies attacking it or
a realm-mate near it. Source checks pin each line's place and the upstream facts the waits mirror.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

Expected: `4 files changed, 61 insertions(+)`.

---

### Task 11: Hooks 1-2: battleground and RvR bots wait at their spot

**Files:**
- Create: `source/server/GameServer/scripts/hearthdaoc/RpTimerWaitController.cs` (a fork part of
  `AutonomousWorldBotController`: the battleground and RvR waits; LF, no BOM)
- Modify: `source/server/GameServer/bots/autonomous/AutonomousWorldBotController.Battleground.cs` (hook 1, in
  `ExecuteBattleground` after `_rvrIntent = ...;`; **CRLF**, no BOM)
- Modify: `source/server/GameServer/bots/autonomous/AutonomousWorldBotController.cs` (hook 2, in `ExecuteRvr` after the
  stale-target clear; LF, no BOM)
- Modify: `deploy/tests/test_rp_timer_wait.py` (`ControllerHookTests` and `EndingsTests`, before the main guard; the
  file is then complete)
- Test: `deploy/tests/test_rp_timer_wait.py`; `deploy/tests/test_battlegrounds.py` (unchanged: it must pass as before)

**Spec:** 2.2 (the trip and best speed), 2.3 (leave when time left is no more than the trip; the think wake), 3.1
(battlegrounds: the slot, the 2,500 gate, the first contact point), 3.2 (frontier alone: the bind, the 750 gate, the
destination or death spot, the re-pick hold), 3.3 (siege members: the event keep, the siege job), section 4 (stand,
walk back, status, route reset), 7.3 (the controller part), 7.4 (hooks 1 and 2), 7.5 (no unit test reaches the
controller part), 10.2 (the source checks).

**Interfaces:**
- Consumes: Task 1's `RpWaitSlot.Current` and `bool RpWaitSlot.TrySwap(RpWaitMarker expected, RpWaitMarker next)`,
  `RpWaitMarker`, `RpDeathRecord`, `RpWaitLook`, `RpWaitDecision`, `RpWaitPhase`, `RpWaitCase`, `RpWaitVerdict`,
  `RpWaitAction`, `RpWaitReason`; Task 2's `RpTimerWait.SpotTolerance`, `Vector2 FirstContactPoint(Vector2 arrival,
  Vector2 centralKeep)`, `long TripMilliseconds(double distance, double unitsPerSecond)`, `double Distance2D(Vector3 a,
  Vector3 b)`, `long LeaveTick(long lastDeathTick, int rpWorthSeconds, long tripMilliseconds)` and `int
  ThinkWakeMilliseconds(long leaveTick, long now, double tickDurationMilliseconds, int standardInterval)`; Task 4's
  `Vector3 WaitSpot(RpWaitMarker marker, RpWaitLook look)` and `RpWaitDecision Decide(RpWaitMarker marker, int
  deathCount, RpWaitLook look, long timeLeft, long tripMilliseconds, long now)`; Task 7's
  `RpTimerWaitScript.BOT_RP_TIMER_WAIT`; Task 8's `RpWaitSlot SlotOf(GameBot bot)`, `RpDeathRecord
  DeathRecordOf(GameBot bot)`, `long RealmPointDeathTick(GameBot bot)`, `long WorthlessFor(GameBot bot)`, `double
  BestSpeed(GameBot bot)`, `string Seconds(long milliseconds)`, `void WriteStart(GameBot bot, RpWaitMarker started, long
  timeLeft, long tripMilliseconds, long leaveInMilliseconds)`, `void WriteSkip(GameBot bot, RpWaitCase hookCase, long
  timeLeft, RpWaitReason reason)` and `void WriteLeave(GameBot bot, RpWaitMarker waiting, long now, long timeLeft, long
  tripMilliseconds, RpWaitReason reason)` (all in `DOL.GS.HearthDAoC`). The controller's privates: `bool
  IssuePath(GameBot bot, Vector3 destination, Vector3? validatedContinuation = null, bool preciseArrival = false, bool
  retargetWhileMoving = false)`, `void SetStatus(GameBot bot, string activity, string goal, string progress, string
  target = "", string destination = "", bool forceSave = false)`, `void SetBattlegroundStatus(GameBot bot,
  BattlegroundBrackets.Bracket bracket, string activity, string detail, string target = "")`, `void
  ResetRouteOrderState()`, `void ReleaseSiegeJob(GameBot bot)` (which clears `_siegeJobKeep`, Siege.cs:469; the part
  never reads `_siegeJobKeep`), `long _keepStallSince`, `CampDestination _rvrDestination` (`Id`, `ZoneName`, `RegionId`,
  `X`, `Y`, `Z`) and `long _nextRvrPlanReview`. Upstream statics: `BattlegroundBrackets.BotArrival(Bracket bracket,
  eRealm realm)` (`GameLocation`), `AutonomousTownTeleporters.Arrival(DbTeleport destination, int slot)` (`Vector3`,
  navmesh-snapped), `GameRelic.IsPlayerCarryingRelic(GameLiving player)`, `GameLoop.GameLoopTime`,
  `GameLoop.TickDuration`, `Properties.RP_WORTH_SECONDS`; `BotBrain.ThinkInterval` (`int { get; set; }`). In
  `test_rp_timer_wait.py`, Task 7's `source`, `between`, `marked`, `cs_files` and its path constants (`ROOT`,
  `GAME_SERVER`, `FORK`, `DECISIONS_CS`, `SCRIPT_CS`, `CONTROLLER_CS`, `WBC`, `BG`, `FT`, `GC`, `KEEP_TRAVEL`, `SIEGE`).
- Produces: in `namespace DOL.GS`, a fork part of `public sealed partial class AutonomousWorldBotController` with
  `private const string RpWaitActivity = "Waiting out the realm point timer"`, `private bool
  RpTimerWaitBattleground(BotBrain brain, GameBot bot, BattlegroundBrackets.Bracket bracket, AbstractGameKeep central)`,
  `private bool RpTimerWaitRvr(BotBrain brain, GameBot bot, bool battleActive, bool dynamicWarband, bool keepPlan)`,
  `private (bool Known, ushort Region, Vector3 Point) RpWaitFrontierTarget(GameBot bot, int deathCount)` and `private
  bool RpWaitAct(BotBrain brain, GameBot bot, RpWaitSlot slot, RpWaitDecision decision, long timeLeft, long
  tripMilliseconds, bool tripKnown, long now, BattlegroundBrackets.Bracket bracket)`; two upstream lines, each under
  its own `// HearthDAoC:` comment line (4 inserted lines, no deletions):
  - hook 1, BG `ExecuteBattleground`: `if (RpTimerWaitBattleground(brain, bot, bracket, central)) return true;`
  - hook 2, WBC `ExecuteRvr`: `if (RpTimerWaitRvr(brain, bot, battleActive, dynamicWarband, committedPlan != null))
    return true;`
  - In the source checks: `ControllerHookTests` (5 tests) and `EndingsTests` (2 tests).

- [ ] **Step 1: Write the failing tests.** The source checks of 10.2 for hooks 1-2 and the controller part.
`ControllerHookTests` pins hook 1 in `ExecuteBattleground` after the over-cap check, the region check and the
`_rvrIntent` line, before the siege job and the roam (so only bots inside their battleground wait, and every role
waits), and hook 2 in `ExecuteRvr` after the rally and muster return and the stale-target clear, before the siege job
(so a finished event is not measured, and nothing re-tasks a waiting bot); `marked` (Task 7) checks that each call
occurs once with a `// HearthDAoC:` comment on the line above it. It also counts `RpTimerWait` in every upstream `.cs`
file (BG 1, WBC 2, GC 2, FT 1: the comment lines say "realm point timer", never the name), checks that the part is a
file-scoped `DOL.GS` part of the controller with the two hook members, and that the private members it uses are still
upstream's, `ReleaseSiegeJob` still clearing `_siegeJobKeep`. `EndingsTests` checks that the four upstream files keep
their endings (BG CRLF, the other three LF, none with a BOM) and that the five fork C# files and this test file are
LF, with no BOM and no tab. The controller part has no unit test (spec 7.5: it needs a controller, a world and the
navmesh); its decisions are Task 4's `Decide` and `WaitSpot` and its arithmetic Task 2's, all unit-tested. Both
classes go after `UpstreamFactTests`, before the main guard (the old text occurs once in the file as Task 10 left it):

```bash
python3 /tmp/hdc-edit.py deploy/tests/test_rp_timer_wait.py <<'EDIT'
<<<<<<< OLD
        self.assertIn("public static Vector3 RendezvousFormationPoint(GameBot bot, string groupId, Vector3 center, bool tight)",
                      source(GC))


if __name__ == "__main__":
=======
        self.assertIn("public static Vector3 RendezvousFormationPoint(GameBot bot, string groupId, Vector3 center, bool tight)",
                      source(GC))


class ControllerHookTests(unittest.TestCase):
    def test_the_battleground_wait_comes_after_the_region_check_and_before_every_role(self):
        tour = between(source(BG), "private bool ExecuteBattleground(", "private bool RoamBattleground(")
        call = "if (RpTimerWaitBattleground(brain, bot, bracket, central)) return true;"
        marked(self, tour, call)
        self.assertLess(tour.index("BotOverCap("), tour.index(call))
        self.assertLess(tour.index("bot.CurrentRegionID != bracket.RegionId"), tour.index(call))
        self.assertLess(tour.index("_rvrIntent = assault ?"), tour.index(call))
        self.assertLess(tour.index(call), tour.index("TryRunSiegeJob(bot)"))
        self.assertLess(tour.index(call), tour.index("return RoamBattleground("))

    def test_the_rvr_wait_comes_after_the_musters_and_the_stale_target_clear(self):
        rvr = between(source(WBC), "private bool ExecuteRvr(BotBrain brain, GameBot bot)", "GameLiving enemy = FindRvrTarget(bot);")
        call = "if (RpTimerWaitRvr(brain, bot, battleActive, dynamicWarband, committedPlan != null)) return true;"
        marked(self, rvr, call)
        self.assertLess(rvr.index("return HandleSiegeRally(bot, forceId, rally);"), rvr.index(call))
        self.assertLess(rvr.index("_nextRvrPlanReview = 0;"), rvr.index(call))
        self.assertLess(rvr.index(call), rvr.index("if (TryRunSiegeJob(bot)) return true;"))

    def test_the_fork_is_called_from_upstream_files_only_by_the_six_hooks(self):
        calls = {}
        for path in cs_files(GAME_SERVER):
            if path.startswith(FORK + os.sep):
                continue
            count = source(path).count("RpTimerWait")
            if count:
                calls[os.path.basename(path)] = count
        self.assertEqual(calls, {
            "AutonomousWorldBotController.Battleground.cs": 1,
            "AutonomousWorldBotController.cs": 2,
            "AutonomousBotGroupCoordinator.cs": 2,
            "AutonomousWorldBotController.FrontierThreat.cs": 1,
        })

    def test_the_controller_part_is_a_partial_of_the_controller(self):
        text = source(CONTROLLER_CS)
        self.assertIn("namespace DOL.GS;\n", text)
        self.assertIn("public sealed partial class AutonomousWorldBotController\n", text)
        self.assertIn("private bool RpTimerWaitBattleground(BotBrain brain, GameBot bot, BattlegroundBrackets.Bracket bracket,", text)
        self.assertIn("private bool RpTimerWaitRvr(BotBrain brain, GameBot bot, bool battleActive, bool dynamicWarband, bool keepPlan)", text)

    def test_the_private_members_the_controller_part_uses_are_upstreams(self):
        wbc, bg, keep, siege = source(WBC), source(BG), source(KEEP_TRAVEL), source(SIEGE)
        self.assertIn("private bool IssuePath(GameBot bot, Vector3 destination, Vector3? validatedContinuation = null,", wbc)
        self.assertIn("private void SetStatus(\n            GameBot bot,\n            string activity,", wbc)
        self.assertIn("private void ResetRouteOrderState()", wbc)
        self.assertIn("private CampDestination _rvrDestination;", wbc)
        self.assertIn("private long _nextRvrPlanReview;", wbc)
        self.assertIn("private void SetBattlegroundStatus(GameBot bot, BattlegroundBrackets.Bracket bracket, string activity, string detail, string target = \"\")", bg)
        self.assertIn("private long _keepStallSince;", keep)
        self.assertIn("private void ReleaseSiegeJob(GameBot bot)", siege)
        # The part never reads _siegeJobKeep; it relies on ReleaseSiegeJob clearing it (spec 3.3, Siege.cs:469).
        self.assertIn("_siegeJobKeep=null;", between(siege, "private void ReleaseSiegeJob(GameBot bot)", "\n        }"))


class EndingsTests(unittest.TestCase):
    def test_the_upstream_files_keep_their_endings(self):
        for path, crlf in ((BG, True), (WBC, False), (GC, False), (FT, False)):
            with open(path, "rb") as f:
                raw = f.read()
            self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n") if crlf else 0, path)
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), path)

    def test_the_fork_files_are_lf_without_bom(self):
        tests = os.path.join(ROOT, "source", "server", "Tests", "UnitTests")
        for path in (DECISIONS_CS, SCRIPT_CS, CONTROLLER_CS, os.path.join(tests, "UT_RpTimerWait.cs"),
                     os.path.join(tests, "UT_RpTimerWaitScript.cs"), os.path.abspath(__file__)):
            with open(path, "rb") as f:
                raw = f.read()
            self.assertNotIn(b"\r", raw, path)
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), path)
            self.assertNotIn(b"\t", raw, path)


if __name__ == "__main__":
>>>>>>> NEW
EDIT
```

Expected: `edited deploy/tests/test_rp_timer_wait.py (1 block(s))`.

- [ ] **Step 2: Run them and watch them fail.**

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_rp_timer_wait.py`
Expected: the progress line `FEF.FE.....................`, then three failures and two errors (the hooks are not in
the upstream files yet, and the part does not exist; the path printed is the repository's own):

```
ERROR: test_the_controller_part_is_a_partial_of_the_controller (tests.test_rp_timer_wait.ControllerHookTests.test_the_controller_part_is_a_partial_of_the_controller)
FileNotFoundError: [Errno 2] No such file or directory: '/home/farral/github/HearthDAoC-rp/source/server/GameServer/scripts/hearthdaoc/RpTimerWaitController.cs'
ERROR: test_the_fork_files_are_lf_without_bom (tests.test_rp_timer_wait.EndingsTests.test_the_fork_files_are_lf_without_bom)
FileNotFoundError: [Errno 2] No such file or directory: '/home/farral/github/HearthDAoC-rp/source/server/GameServer/scripts/hearthdaoc/RpTimerWaitController.cs'
FAIL: test_the_battleground_wait_comes_after_the_region_check_and_before_every_role (tests.test_rp_timer_wait.ControllerHookTests.test_the_battleground_wait_comes_after_the_region_check_and_before_every_role)
AssertionError: 0 != 1 : if (RpTimerWaitBattleground(brain, bot, bracket, central)) return true;
FAIL: test_the_fork_is_called_from_upstream_files_only_by_the_six_hooks (tests.test_rp_timer_wait.ControllerHookTests.test_the_fork_is_called_from_upstream_files_only_by_the_six_hooks)
AssertionError: {'AutonomousBotGroupCoordinator.cs': 2, 'AutonomousWo[72 chars]': 1} != {'AutonomousWorldBotController.Battleground.cs': 1, '[123 chars]': 1}
FAIL: test_the_rvr_wait_comes_after_the_musters_and_the_stale_target_clear (tests.test_rp_timer_wait.ControllerHookTests.test_the_rvr_wait_comes_after_the_musters_and_the_stale_target_clear)
AssertionError: 0 != 1 : if (RpTimerWaitRvr(brain, bot, battleActive, dynamicWarband, committedPlan != null)) return true;
```

(the counts check's diff shows `AutonomousWorldBotController.Battleground.cs` missing and
`AutonomousWorldBotController.cs` at 1, its hook 3 only), then `Ran 27 tests` and `FAILED (failures=3, errors=2)`. The
other new tests pass already: `test_the_private_members_the_controller_part_uses_are_upstreams` and
`test_the_upstream_files_keep_their_endings` pin upstream as it is.

- [ ] **Step 3: Implement.** Create `source/server/GameServer/scripts/hearthdaoc/RpTimerWaitController.cs` with exactly
the code below (LF, no BOM, spaces): its usings, header comment and members, each under its rule comment (the
WBC line numbers in the comments are those at 56fbe98), with these bodies:

- Both hooks read the slot's marker first and return false at once for no marker, no `PersistentRecord`, a marker for
  another death count, or a Left marker; then the switch (off: false). So a bot with no wait costs one dictionary read,
  and with the switch off no wait is held (hook 3, on the same turn before them, has already ended any).
- `RpTimerWaitBattleground` (hook 1) takes its realm's arrival point (none: false, which no realm of a bot gives); the
  target is the first contact point (Task 2) on the line from it to the central keep, at the arrival's height, in the
  battleground (no central keep: no target); for a Released marker only, the slot `1 + ObjectID % 12` of
  `AutonomousTownTeleporters.Arrival` around the arrival point (a navmesh query, made only at the first look, which
  stores it as the spot). The trip is from `WaitSpot` to the target at the bot's best speed (`long.MaxValue` with no
  target), then `Decide` and `RpWaitAct` with the bracket.
- `RpTimerWaitRvr` (hook 2) classifies the turn: a battle with a keep plan is a siege, a dynamic warband outside battle a
  warband (the gate's), anything else frontier; a relic carrier, a destination starting `rvr-relic-carrier-` or a battle
  with no keep plan is a relic. The siege's target is the event keep (`_rvrDestination`, whose id the look carries), the
  frontier's `RpWaitFrontierTarget`, the warband's none. A target in another region gives no trip (`long.MaxValue`, and
  `-` in the log): `Decide` says other-region before it compares times.
- `RpWaitFrontierTarget`: the destination in the bot's region, else this death's death spot in the bot's region, else
  either one in its own region (other-region), else none (no-target).
- `RpWaitAct`: Ignore goes on (false). A Skip or Leave swaps against the marker read (a lost swap writes and logs
  nothing: false), then writes its skip line (none for a bot already worth points), or its leave line with the route
  reset and `_keepStallSince = 0`; a frontier solo leaving at its moment (`Skip(Trip)` or `Leave(Due)`, time left above
  0) keeps its destination until it is worth points (`_nextRvrPlanReview`); false. A Start or Convert swaps (lost:
  false), writes its lines (a Convert first `leave reason=battle`), stops the bot, frees its siege job and resets its
  route state, then holds. A Hold walks to the spot when `Decide` says so, or keeps a walk to it going (a path still
  more than 48 from it), else stands; sets the status with the countdown (a battleground's through
  `SetBattlegroundStatus`; RvR's phase and `SetStatus` with "Active frontier RvR", never a forced save); and wakes the
  next think at the leave moment (`ThinkWakeMilliseconds`, from the standard interval the brain has just set); true.

```csharp
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
```

Hook 1, in `ExecuteBattleground` after the `_rvrIntent` line: after the over-cap check and the region check, so only
bots inside their battleground wait; before the siege job, the assault, the defence and the roam, so every role waits.
Returning true skips `FSM.Think`. It adds no `TravelToBattleground(` and no `ClassicBattlegroundsScript` call, so
`test_battlegrounds.py` passes unchanged. The file is CRLF: the helper sees CRLF in it and turns the block's LF line
ends into CRLF in both the old and the new text, so the two new lines are CRLF like the rest (copy the block as it is,
with LF):

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/bots/autonomous/AutonomousWorldBotController.Battleground.cs <<'EDIT'
<<<<<<< OLD
            _rvrIntent = assault ? AutonomousRvrEventLayer.Intent.AssaultKeep : AutonomousRvrEventLayer.Intent.Roam;

            if (assault)
=======
            _rvrIntent = assault ? AutonomousRvrEventLayer.Intent.AssaultKeep : AutonomousRvrEventLayer.Intent.Roam;
            // HearthDAoC: back from a death and worth no realm points yet: wait at the arrival point.
            if (RpTimerWaitBattleground(brain, bot, bracket, central)) return true;

            if (assault)
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/GameServer/bots/autonomous/AutonomousWorldBotController.Battleground.cs (1 block(s))`.

Hook 2, in `ExecuteRvr` after the stale-target clear: after the rally and muster returns (a muster is a wait already),
the warband pull hold and the solo staging gate; before the siege job, the target search, the relic branches and the
re-pick, so nothing moves or re-tasks a waiting bot. Solo roamers reach it, and so do battle forces. The file is LF (the
OLD text occurs once in it as Task 10 left it):

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/bots/autonomous/AutonomousWorldBotController.cs <<'EDIT'
<<<<<<< OLD
                _nextRvrPlanReview = 0;
            }

            // RvR has no PvE puller. Every cohesive member can acquire a local
=======
                _nextRvrPlanReview = 0;
            }
            // HearthDAoC: back from a death and worth no realm points yet: wait at the bind.
            if (RpTimerWaitRvr(brain, bot, battleActive, dynamicWarband, committedPlan != null)) return true;

            // RvR has no PvE puller. Every cohesive member can acquire a local
>>>>>>> NEW
EDIT
```

Expected: `edited source/server/GameServer/bots/autonomous/AutonomousWorldBotController.cs (1 block(s))`.

- [ ] **Step 4: Run them and watch them pass.**

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_rp_timer_wait.py`
Expected: `Ran 27 tests` and `OK`.

Run: `python3 -B -m unittest discover -s deploy/tests -t deploy -p test_battlegrounds.py`
Expected: `Ran 35 tests` and `OK (skipped=10)` (unchanged; the ten need `HDC_TEST_WORLD`).

Run: `dotnet build source/server/Tests/Tests.csproj --nologo -v q -clp:ErrorsOnly`
Expected: `Build succeeded.` and `0 Error(s)`; the warning total varies by a few between builds of the same tree
(634 or 639 while the plan was written), and no warning names a file this task changes.

CI's unit filter (the full command of Global Constraints, with its prefix); this task adds no unit test, so the count
is Task 9's:

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_CommandPrivLevelOverrides|FullyQualifiedName~UT_SiStartChoice|FullyQualifiedName~UT_ClassicBattlegrounds|FullyQualifiedName~UT_DataQuestDependency|FullyQualifiedName~UT_DataQuestDeliveryItem|FullyQualifiedName~UT_DataQuestOffers|FullyQualifiedName~UT_QuestJournal|FullyQualifiedName~UT_DataQuestWhisper|FullyQualifiedName~UT_QuestNames|FullyQualifiedName~UT_ClassicQuestsExtra|FullyQualifiedName~UT_ClassicQuestsChoice|FullyQualifiedName~UT_LinkedCamps|FullyQualifiedName~UT_EpicChain|FullyQualifiedName~UT_QuestIndicatorProbe|FullyQualifiedName~UT_QuestIndicators|FullyQualifiedName~UT_IndicatorSentStore|FullyQualifiedName~UT_RpTimerWait|FullyQualifiedName~UT_RpTimerWaitScript"`
Expected: `Passed!  - Failed:     0, Passed:   608, Skipped:     0, Total:   608` (424 at 56fbe98, Tasks 1-6's 160, Task 7's 1,
Task 8's 19 and Task 9's 4).

Both whole suites, one after the other (not at the same time). Every unit test:

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_"`
Expected: `Passed!  - Failed:     0, Passed:  3333, Skipped:     0, Total:  3333` (3,149 at 56fbe98 and this plan's 184;
about 30 s).

The whole deploy suite, from `deploy/`:

Run: `(cd deploy && HDC_TEST_WORLD=/home/farral/Games/OfflineDAoC-archive/test-world/clean-classic-0.35.db HDC_CLASSIC_QUESTS=/home/farral/Games/DAoC/research/gos-epic-2026-10-09/classic-quests.json python3 -m unittest discover -s tests -t .)`
Expected: `Ran 627 tests` and `OK (skipped=11)` (Task 10's 620 and this task's 7; about two minutes).

Run: `git diff --stat`
Expected: only these three files (the new part is not tracked until Step 5's `git add`), the two upstream ones with 2
insertions each and no deletions (git may shorten the paths to fit the terminal, as here):

```
 deploy/tests/test_rp_timer_wait.py                 | 74 ++++++++++++++++++++++
 .../AutonomousWorldBotController.Battleground.cs   |  2 +
 .../autonomous/AutonomousWorldBotController.cs     |  2 +
 3 files changed, 78 insertions(+)
```

All six hooks against the approved spec's commit:

Run: `git diff --stat 56fbe98 -- source/server/GameServer/bots/autonomous/AutonomousWorldBotController.Battleground.cs source/server/GameServer/bots/autonomous/AutonomousWorldBotController.cs source/server/GameServer/bots/autonomous/AutonomousBotGroupCoordinator.cs source/server/GameServer/bots/autonomous/AutonomousWorldBotController.FrontierThreat.cs`
Expected: the four upstream files, `12 insertions(+)` and no deletions (GC 4, BG 2, FT 2, WBC 4):

```
 .../GameServer/bots/autonomous/AutonomousBotGroupCoordinator.cs       | 4 ++++
 .../bots/autonomous/AutonomousWorldBotController.Battleground.cs      | 2 ++
 .../bots/autonomous/AutonomousWorldBotController.FrontierThreat.cs    | 2 ++
 .../server/GameServer/bots/autonomous/AutonomousWorldBotController.cs | 4 ++++
 4 files changed, 12 insertions(+)
```

- [ ] **Step 5: Commit.**

```bash
git add source/server/GameServer/scripts/hearthdaoc/RpTimerWaitController.cs source/server/GameServer/bots/autonomous/AutonomousWorldBotController.Battleground.cs source/server/GameServer/bots/autonomous/AutonomousWorldBotController.cs deploy/tests/test_rp_timer_wait.py
git commit -F - <<'EOF'
feat(rp-wait): released bots wait at their spot until they can arrive worth realm points

A fork part of the bot controller holds the two waits. At a battleground's arrival point, a bind, or a drafted
warband's slot, a released bot stands, rests and rebuffs, and its next think is woken at its leave moment; it
leaves when its time left is no more than its trip to the first contact point, its frontier destination or the
event keep. Its siege job is freed and its route state reset when the wait starts and ends, and a frontier solo
keeps its destination until it is worth points again. Two marked upstream lines call it.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

Expected: `4 files changed, 302 insertions(+)` and `create mode 100644
source/server/GameServer/scripts/hearthdaoc/RpTimerWaitController.cs`.

---

### Task 12: The record and the owner's in-game checks

**Files:**
- Modify: `docs/fork/FORK.md` (a row at the end of the server-code table, after the quest indicators row and before
  `## Client patches`; LF, no BOM)
- Create: `docs/fork/verification/rp-timer-waits-ingame.md` (the owner's in-game checks, filled in with the results
  after the run; LF, no BOM, no tabs)
- Test: none new; the full verification (CI's unit filter, every `UT_` test, the whole deploy suite)

**Spec:** 10.4 (the nine checks), 10.5 (what to read in the log), 11 (documentation).

**Interfaces:**
- Consumes: no code. The two documents name what Tasks 1-11 built: the fork files `RpTimerWait.cs`,
  `RpTimerWaitScript.cs` and `RpTimerWaitController.cs`; the six marked upstream lines in
  `AutonomousWorldBotController.Battleground.cs` (`ExecuteBattleground`), `AutonomousWorldBotController.cs` (`Tick`,
  `ExecuteRvr`), `AutonomousBotGroupCoordinator.cs` (`TryFormGroups`' recruiting filter, the regroup completion in
  `UpdateSession`) and `AutonomousWorldBotController.FrontierThreat.cs` (the threat scan); the `bot_rp_timer_wait`
  property and `HEARTHDAOC_BOT_RP_TIMER_WAIT` (Task 7: `server_properties.py` prints "Bot realm point timer wait: on"
  or "off" when it changes the row, and `./hdc update` adds the setting to `.env`); the four `HEARTHDAOC_RP_WAIT`
  lines, `action=died`, `start`, `skip` and `leave`, with the fields and words of Global Constraints (Task 8's
  builders, Task 9's handlers, Task 11's waits); upstream's `RVR_BOT_KILLED` line, whose first fields are
  `victim=<name> id=<id>` (ARPR:70-73); the battleground regions 250-253 and `BattlegroundBrackets.BotArrival` (Albion
  36428, 51260, 3952; Midgard 53150, 26093, 4263; Hibernia 19714, 19085, 4094).
- Produces: the FORK.md server-code row (byte for byte as Step 1 gives it); the guide: the update (check 1), how to
  read the log (`docker exec hearthdaoc-server grep HEARTHDAOC_RP_WAIT /data/logs/server.log`, since `./hdc logs` keeps
  only 200 lines), checks 2-9 of spec 10.4 each with an empty `Result:` line, and the log reads of spec 10.5, each with
  a command.

- [ ] **Step 1: The FORK.md row.** The server-code table (4 columns: Change | Files | Why | Upstream) ends with the
  quest indicators row; the new row goes after it, before `## Client patches`:

```bash
python3 /tmp/hdc-edit.py docs/fork/FORK.md <<'EDIT'
<<<<<<< OLD
and the KillFinish fix; the scheme is fork-only |

## Client patches
=======
and the KillFinish fix; the scheme is fork-only |
| Gamebots come back worth realm points (stage 1): released bots wait out the realm point timer; `bot_rp_timer_wait` server property | `GameServer/scripts/hearthdaoc/RpTimerWait.cs` (new: the decisions), `GameServer/scripts/hearthdaoc/RpTimerWaitScript.cs` (new: the property, the game wiring, the `Dying` and `MemberJoined` handlers, the `HEARTHDAOC_RP_WAIT` log), `GameServer/scripts/hearthdaoc/RpTimerWaitController.cs` (new: a fork part of `AutonomousWorldBotController`, the battleground and RvR waits); six lines, each marked: `bots/autonomous/AutonomousWorldBotController.Battleground.cs` (`ExecuteBattleground`), `bots/autonomous/AutonomousWorldBotController.cs` (`Tick`, `ExecuteRvr`), `bots/autonomous/AutonomousBotGroupCoordinator.cs` (`TryFormGroups`' recruiting filter, the regroup completion in `UpdateSession`), `bots/autonomous/AutonomousWorldBotController.FrontierThreat.cs` (the threat scan); `HEARTHDAOC_BOT_RP_TIMER_WAIT` in `deploy/bin/server_properties.py`, `deploy/entrypoint.sh`, `deploy/compose.yml`, `deploy/.env.example`; tests `Tests/UnitTests/UT_RpTimerWait.cs`, `Tests/UnitTests/UT_RpTimerWaitScript.cs`, source and deploy checks `deploy/tests/test_rp_timer_wait.py` | Released gamebots ran straight back and arrived worth no realm points (owner, 2026-10-12: "i'd like to keep the timer, but make the bots smarter"; [spec](specs/2026-10-13-rp-timer-waits-design.md), stage 1). The timer is unchanged. A released bot waits at a safe spot (its realm's battleground arrival point, its bind, or its warband's slot) and leaves when its time left is no more than its straight-line trip back at its best speed; a frontier warband leaves together; a bot resurrected where it fell fights on. Waiting bots fight back but charge nothing they only see, and join no new warband. Every battleground bot leaves at its own moment: waves are a later stage | Fork-only: six marked lines and a partial of the controller; a candidate later, only with the owner's go-ahead |

## Client patches
>>>>>>> NEW
EDIT
```

Expected: `edited docs/fork/FORK.md (1 block(s))`.

- [ ] **Step 2: The in-game checks.** Create `docs/fork/verification/rp-timer-waits-ingame.md` with exactly this (the
  quoted heredoc keeps every `$`, backtick and backslash as written; the file is 214 lines and ends with one newline):

````bash
cat > docs/fork/verification/rp-timer-waits-ingame.md <<'GUIDE'
# Gamebots come back worth realm points (stage 1): in-game checks

For the owner, after the release with the realm point waits is installed (`./hdc update`). The design is in the
[spec](../specs/2026-10-13-rp-timer-waits-design.md); these are its checks (section 10.4) and its log reads (10.5).
Write what you saw on each check's "Result:" line: pass or fail, and anything odd. Log lines pasted in are welcome.

- Date:
- Release (`HEARTHDAOC_TAG` in `~/hearthdaoc/.env`):

What changes: a gamebot killed in RvR or a battleground and released waits at a safe spot (its realm's arrival point in
a battleground, its bind in the frontier, or its warband's slot at the border keep). It leaves when its time left is no
more than its trip back, so it arrives just as it is worth realm points again, 300 s after its last death. The timer
itself is unchanged. A bot resurrected where it fell fights on. Waiting bots rest and rebuff and fight back when they
or a realm-mate near them are attacked, but don't run at enemies they only see. In this stage every battleground bot
leaves at its own moment (no waves).

## Reading the server log

Each event writes one line starting `HEARTHDAOC_RP_WAIT` to the server log. `./hdc logs` keeps only the last 200
lines, so read the log file itself, on the server, from `~/hearthdaoc`:

```bash
docker exec hearthdaoc-server grep HEARTHDAOC_RP_WAIT /data/logs/server.log
```

Add `| tail -20` for the latest lines, or `| grep 'bot=<name>'` for one bot. Each line starts with its date and time
(`MM/dd HH:mm:ss`). The server may start a new log file at midnight: `docker exec hearthdaoc-server ls /data/logs`
shows the older ones beside `server.log`.

| Line | Written when | What to read |
|---|---|---|
| `action=died` | a gamebot is killed by another realm (a player, an enemy bot, a guard or a pet), with the switch on or off | `worth=yes` (the kill paid realm points) or `worth=no` (it paid none); `sinceLastDeath=` seconds since its previous death (`none`: no earlier death since the server started); `region=` |
| `action=start` | a wait starts | `case=` (`battleground`, `frontier`, `siege` or `warband`); `worthIn=` seconds until it is worth points; `trip=` seconds to walk back; `leaveIn=` seconds until it leaves; `spot=`; `group=` for a warband |
| `action=skip` | a released bot still worth nothing doesn't wait | `reason=`: `trip` (it arrives worth points anyway), `other-region`, `moved-away`, `relic` or `no-target` |
| `action=leave` | a wait ends | `waited=` seconds; `reason=`: `due` (its time), `died`, `player-group`, `off`, `changed`, `called`, `battle`, `moved-away`, `relic`, `no-target` or `other-region` |

Regions: the battlegrounds are 253 Abermenai (levels 15-19), 252 Thidranki (20-24), 251 Murdaigean (25-29) and 250
Caledonia (30-35); the frontiers are 1 (Albion), 100 (Midgard) and 200 (Hibernia).

The arrival points outside the portal keeps, the same in all four battlegrounds: Albion 36428, 51260 (Z 3952), Midgard
53150, 26093 (Z 4263), Hibernia 19714, 19085 (Z 4094). Inside a battleground a GM gets to Albion's with
`/jump to 36428 51260 3952`.

Every line counted by kind, case, reason and worth, for checks 7 and 9 and the reads at the end:

```bash
docker exec hearthdaoc-server grep HEARTHDAOC_RP_WAIT /data/logs/server.log |
  awk '{ k = ""; for (i = 1; i <= NF; i++) if ($i ~ /^(action|case|reason|worth)=/) k = k " " $i; n[k]++ }
       END { for (k in n) print n[k] k }' | sort -k2
```

To read only part of the log, for example a few hours with the switch on and then a few with it off, add a time filter
right after the `grep` of any command here, with the month/day and hour:minute you switched. For example, the counts
from 18:00 to 21:00 on 14 October:

```bash
docker exec hearthdaoc-server grep HEARTHDAOC_RP_WAIT /data/logs/server.log |
  awk '$0 >= "10/14 18:00" && $0 < "10/14 21:00"' |
  awk '{ k = ""; for (i = 1; i <= NF; i++) if ($i ~ /^(action|case|reason|worth)=/) k = k " " $i; n[k]++ }
       END { for (k in n) print n[k] k }' | sort -k2
```

## The checks

### 1. The update

`./hdc update` lists `HEARTHDAOC_BOT_RP_TIMER_WAIT` among the new settings added to `.env`, and `.env` has
`HEARTHDAOC_BOT_RP_TIMER_WAIT=on`. The first start after the update prints "Bot realm point timer wait: on":

```bash
grep HEARTHDAOC_BOT_RP_TIMER_WAIT ~/hearthdaoc/.env
docker logs hearthdaoc-server 2>&1 | grep 'Bot realm point timer wait'
```

Result:

### 2. Battleground: a death and its wait

With a character of a battleground's levels, kill an enemy bot near the central keep. The log shows its `died …
worth=yes`, then about 30 s later `start case=battleground` with `trip=11` (an Albion bot) or about `trip=43` (Midgard,
Hibernia).

Its `leave reason=due` comes about the `start`'s `leaveIn` seconds after the `start` (`waited=` on the `leave` line),
or up to about 12 s later: a standing bot thinks only every few seconds, and a rebuff can take the turn it was woken
for. A bot still fighting at its moment leaves later, on its first turn after the fight ends (10 s after the last
blow); that is expected, never early.

Result:

### 3. At the arrival point

Go to that realm's arrival point outside its portal keep (the coordinates above). Its waiting bots stand there, apart,
each at its own spot about 160-330 from the point, and don't run at you, even one just arriving through the teleporter.
Hit one: it, and its realm-mates within 1,000, fight back; after the fight they walk back to their spots and wait on (a
fight writes no `leave`).

Result:

### 4. Leaving, and worth points in the field

At its `leave` a bot walks out on its own (no waves in this stage). Kill it in the field: you get realm points, with no
"has been killed recently and is worth no realm points!" message, and the log shows `died … worth=yes`.

As in check 2, each `leave reason=due` comes about its `start`'s `leaveIn` after the `start`, or up to about 12 s
later, unless it was fighting at its moment.

Result:

### 5. A kill while it waits

Kill a bot while it waits: you get the "worth no realm points" message, as expected, and the log shows `died …
worth=no` and, at the same death, `leave reason=died`. After its next release it gets a new `start`. A warband member
resurrected at its slot instead gets no new `start`.

(A bot killed by a monster while it waits also gets `leave reason=died`, with no `died` line: `died` lines are only for
kills by another realm.)

Result:

### 6. A player's invite

Invite a waiting bot into your group: `leave reason=player-group`. Remove it from the group before its timer runs out:
it doesn't walk back to its spot.

Result:

### 7. Frontier, over a day of play

In the counts (above): `start case=frontier` and `start case=siege` for defenders near their home binds (Fensalir
Faste, Mjollner Faste, Dun Ailinne …); `skip … reason=other-region` for invaders, who release in their capital;
`start case=warband` with a `group=`, one per released member at the warband's slots, and one `leave` each when the
warband sets out together (`docker exec hearthdaoc-server grep 'case=warband' /data/logs/server.log`).

Result:

### 8. At a home bind

Hit one waiting bot at a home bind: it fights back; its solo neighbours do not. That is expected: the bots' threat scan
is off at a bind, so only a bot that is attacked answers.

Result:

### 9. Off

Set `HEARTHDAOC_BOT_RP_TIMER_WAIT=off` in `~/hearthdaoc/.env`, then `./hdc up`: the start prints "Bot realm point
timer wait: off" (`docker logs hearthdaoc-server 2>&1 | grep 'Bot realm point timer wait'`). From then on, no `start`
lines; `died` lines still come; bots run straight back as before. Note the time, for the comparison below. Afterwards
set it back to `on` and `./hdc up` again.

Result:

## Reading the log over hours

Run these from `~/hearthdaoc` after some hours of play. A server restart ends every wait without a `leave` line (the
timer and the waits are kept in memory only), so lines from before a restart can show a `start` with no `leave`.

**Every `start` has exactly one `leave`.** The last two numbers should be 0 (except across a restart). The middle one
is how many bots are sitting out at the last line read; to see it at another moment, add a time filter such as
`awk '$0 < "10/14 20:00"' |` after the `grep`.

```bash
docker exec hearthdaoc-server grep -E 'HEARTHDAOC_RP_WAIT action=(start|leave) ' /data/logs/server.log |
  awk '{ id = $0; sub(/.* id=/, "", id); sub(/ .*/, "", id)
         if ($0 ~ / action=start /) { starts++; if (open[id]) twice++; open[id] = 1 }
         else { leaves++; if (!open[id]) lone++; open[id] = 0 } }
       END { for (id in open) if (open[id]) still++
             printf "%d starts, %d leaves, %d sitting out; ", starts, leaves, still
             printf "%d starts with no leave before the next, %d leaves with no start\n", twice, lone }'
```

**Kills that paid nothing:** the share of `worth=no` among `died`, in total and per region (250-253 the
battlegrounds; 1, 100 and 200 the frontiers). Compare a few hours with the switch on against a few hours with it off
(the time filter, above).

```bash
docker exec hearthdaoc-server grep 'HEARTHDAOC_RP_WAIT action=died ' /data/logs/server.log |
  awk '{ r = $0; sub(/.* region=/, "", r); sub(/ .*/, "", r); all[r]++; total++
         if ($0 ~ / worth=no /) { no[r]++; none++ } }
       END { for (r in all) printf "region %s: %d of %d kills paid nothing\n", r, no[r], all[r]
             printf "all regions: %d of %d kills paid nothing\n", none, total }' | sort
```

**Before this release:** the same share from the `RVR_BOT_KILLED` lines the server already writes (one per gamebot
killed by another realm): a bot `id=` killed again within 300 s of its previous line paid nothing. It is a lower bound:
deaths to monsters and neutral guards restart the timer too, but write no such line. Use the time filter to stop at the
update.

```bash
docker exec hearthdaoc-server grep 'RVR_BOT_KILLED ' /data/logs/server.log |
  awk 'BEGIN { split("0 31 59 90 120 151 181 212 243 273 304 334", before, " ") }
       { split(substr($0, 1, 14), t, /[\/ :]/)
         s = ((before[t[1] + 0] + t[2]) * 24 + t[3]) * 3600 + t[4] * 60 + t[5]
         id = $0; sub(/.* id=/, "", id); sub(/ .*/, "", id)
         total++; if ((id in last) && s - last[id] < 300) none++; last[id] = s }
       END { printf "%d of %d kills paid nothing (the same bot killed again within 300 s)\n", none, total }'
```

**The cost:** `waited=` on the `leave reason=due` lines. In the battlegrounds about 230-260 s (est.): Albion about
259 s, Midgard and Hibernia about 227 s.

```bash
docker exec hearthdaoc-server grep 'HEARTHDAOC_RP_WAIT action=leave ' /data/logs/server.log |
  awk '/ reason=due/ { c = $0; sub(/.* case=/, "", c); sub(/ .*/, "", c)
         r = $0; sub(/.* realm=/, "", r); sub(/ .*/, "", r)
         w = $0; sub(/.* waited=/, "", w); sub(/ .*/, "", w); n[c " " r]++; sum[c " " r] += w }
       END { for (k in n) printf "%s: %d waits, %d s on average\n", k, n[k], sum[k] / n[k] }' | sort
```

**What remains** (kills that still pay nothing), from the counts above:

- bots killed again at their spot, for example by players camping an arrival point: `leave reason=died`;
- bots resurrected where they fell: they never wait, so their next death can be `worth=no`;
- waits ended early: `leave` reasons other than `due`;
- released bots that didn't wait: the `skip` reasons.
GUIDE
````

The guide's commands run on the owner's server, from `~/hearthdaoc`; nothing in this plan runs them (each was checked
against a sample log while the plan was written).

- [ ] **Step 3: Check the two files.**

Run: `git diff --stat`
Expected: only FORK.md's one line (the guide is not tracked until Step 5's `git add`):

```
 docs/fork/FORK.md | 1 +
 1 file changed, 1 insertion(+)
```

Run: `git status --short`
Expected (`serverconfig.xml` is ignored):

```
 M docs/fork/FORK.md
?? docs/fork/verification/rp-timer-waits-ingame.md
```

Run: `python3 -c "raw = open('docs/fork/verification/rp-timer-waits-ingame.md', 'rb').read(); print(b'\r' in raw, raw.startswith(b'\xef\xbb\xbf'), b'\t' in raw)"`
Expected: `False False False` (no CR, no BOM, no tab).

- [ ] **Step 4: Full verification.** The code is as Task 11 left it, so the counts are Task 11's. Run the suites one
  after the other, not at the same time.

CI's unit filter (the full command of Global Constraints, with its prefix):

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_CommandPrivLevelOverrides|FullyQualifiedName~UT_SiStartChoice|FullyQualifiedName~UT_ClassicBattlegrounds|FullyQualifiedName~UT_DataQuestDependency|FullyQualifiedName~UT_DataQuestDeliveryItem|FullyQualifiedName~UT_DataQuestOffers|FullyQualifiedName~UT_QuestJournal|FullyQualifiedName~UT_DataQuestWhisper|FullyQualifiedName~UT_QuestNames|FullyQualifiedName~UT_ClassicQuestsExtra|FullyQualifiedName~UT_ClassicQuestsChoice|FullyQualifiedName~UT_LinkedCamps|FullyQualifiedName~UT_EpicChain|FullyQualifiedName~UT_QuestIndicatorProbe|FullyQualifiedName~UT_QuestIndicators|FullyQualifiedName~UT_IndicatorSentStore|FullyQualifiedName~UT_RpTimerWait|FullyQualifiedName~UT_RpTimerWaitScript"`
Expected: `Passed!  - Failed:     0, Passed:   608, Skipped:     0, Total:   608` (424 at 56fbe98, Tasks 1-6's 160, Task 7's 1,
Task 8's 19 and Task 9's 4).

Every unit test:

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_"`
Expected: `Passed!  - Failed:     0, Passed:  3333, Skipped:     0, Total:  3333` (3,149 at 56fbe98 and this plan's 184;
about 30 s). If upstream's `PooledWalReadersAndWriters_CanOpenConnectionsConcurrently` fails with "database is locked",
rerun it alone and say so (Global Constraints).

The whole deploy suite, from `deploy/`:

Run: `(cd deploy && HDC_TEST_WORLD=/home/farral/Games/OfflineDAoC-archive/test-world/clean-classic-0.35.db HDC_CLASSIC_QUESTS=/home/farral/Games/DAoC/research/gos-epic-2026-10-09/classic-quests.json python3 -m unittest discover -s tests -t .)`
Expected: `Ran 627 tests` and `OK (skipped=11)` (600 at 56fbe98 and this plan's 27 in `test_rp_timer_wait.py`; about
two minutes).

- [ ] **Step 5: Commit.**

```bash
git add docs/fork/FORK.md docs/fork/verification/rp-timer-waits-ingame.md
git commit -F - <<'EOF'
docs(rp-wait): the fork record and the owner's in-game checks

The record of the fork's new server code and its six marked upstream lines, and the owner's checks after the
release: a battleground death to its wait and its leave, a frontier day's waits, a kill while waiting, a player's
invite, and the switch turned off.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

Expected: `2 files changed, 215 insertions(+)` and `create mode 100644 docs/fork/verification/rp-timer-waits-ingame.md`.

After Task 12 the controller pushes the branch, opens the PR (its description carries the rulings made while writing the plan and a "To
update" section: owner `./hdc update`, which adds `HEARTHDAOC_BOT_RP_TIMER_WAIT=on` to `.env`, no world data change,
then the checks of `docs/fork/verification/rp-timer-waits-ingame.md`; players: nothing) and watches CI.

# Quest indicators: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **After execution (2026-10-11):** the six tasks ran inline (commits 448092c..fc68656). The final review's fixes are
> documentation only, in the commit after fc68656: in-game check 9 now goes past the server's 6,000-unit range (this
> plan's copy says 4,000), and FORK.md and the spec say that `CanShowOneQuest`/`CanFinishOneQuest` are no longer
> called. The review's five minors were then fixed too (owner, 2026-10-11): pure, unit-tested decisions for raw values
> and for the adapter's rules, source checks of their wiring and of the hooks' nesting (each proven against a broken
> copy), no quest effect after a GM's `/indicator create` value, and NPCs that left the world or whose object ID is
> reused get their marker sent again. Rulings are in the PR.

**Goal:** Every NPC shows one quest marker from one set of rules (a yellow knot for a quest to take, a white knot for
the player's current step, a blue knot to turn in), and the marker changes the moment the player's level, class or
quests change.

**Architecture:** A fork file (`scripts/hearthdaoc/QuestIndicators.cs`) holds the rules as a pure function and the
meaning-to-wire table; `GameNPC.GetQuestIndicator` returns the rules' meaning, and the two packet writers the 1.127
client uses translate it to the value the client draws and record it per player and NPC
(`scripts/hearthdaoc/IndicatorSentStore.cs`). One-line hooks in upstream files ask `QuestIndicators.Refresh(player)`,
which, once per game-loop tick, sends the quest effect for each NPC on the client whose value changed.

**Tech Stack:** C# (.NET 10, NUnit 4) for the server and its unit tests; Python 3 `unittest` source checks in
`deploy/tests`; GitHub Actions CI (`.github/workflows/server-image.yml`).

**Spec:** `docs/fork/specs/2026-10-11-quest-indicators-design.md` (approved by the owner 2026-10-11; read it with this
plan). Every code block below was built and tested in a scratch copy of this branch before the plan was written (88
indicator unit tests, CI's whole unit filter 368, `UT_` 3093, `deploy/tests` 414 OK), then dry-run step by step.

## Global Constraints

- Work in `~/github/HearthDAoC-qi`, branch `quest-indicators` (from `main` 09b76ef, v0.35b-hearth.10, plus the spec
  commits). Never commit to `main`; never push to or open anything on `shadowofze/OfflineDAoC` or OpenDAoC. Implementers
  don't push or open PRs; the controller does at the end. Implementers never dispatch subagents.
- Every commit message is `type(scope): a plain lower-case sentence`, a wrapped prose body, and ends with the line
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Line endings and BOMs stay exactly as they are.** Upstream files are CRLF; `PacketLib1124.cs` and `DataQuest.cs`
  also start with a UTF-8 BOM; `GameNPC.cs`, `GamePlayer.cs`, `PacketLib173.cs`, `AbstractQuest.cs` and the three
  `ECS-Services/*QuestService.cs` have no BOM. `GameNPC.cs`, `DataQuest.cs` and the packet files indent with tabs, the
  others with spaces. Edit existing files **only** with the helper below, which keeps both; the edit blocks in this
  plan contain literal tabs where the file has them, so copy each block byte for byte (the quoted heredocs keep them).
  `git diff --stat` must show only your lines.
- New fork files (`scripts/hearthdaoc/*.cs`, `Tests/UnitTests/UT_*.cs`, `deploy/tests/*.py`) are LF, no BOM, with a
  file-scoped namespace, like every existing fork file, even though `source/server/.editorconfig` says CRLF and
  block-scoped. Create them with the Write tool or a quoted heredoc exactly as given.
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

- Run every command, edit block and `git add` from the repository root, `~/github/HearthDAoC-qi`, after checking that
  `git branch --show-current` prints `quest-indicators` (if it prints another name, `git switch quest-indicators`; if it
  prints nothing, you are in a detached checkout: stop and ask the controller).
- Test commands:
  - Unit tests need `source/server/CoreServer/config/serverconfig.xml` (gitignored; never commit it). If it is missing:
    `cp deploy/serverconfig.build.xml source/server/CoreServer/config/serverconfig.xml`.
  - One class: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --filter "FullyQualifiedName~UT_X"`.
    `FullyQualifiedName~UT_QuestIndicators` does not match `UT_QuestIndicatorProbe` (no `s`).
  - Source checks: `python3 -B -m unittest deploy/tests/test_quest_indicators.py`.
  - Everything: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --filter "FullyQualifiedName~UT_"`
    and `HDC_TEST_WORLD=/home/farral/Games/OfflineDAoC-archive/test-world/clean-classic-0.35.db python3 -B -m unittest discover -s deploy/tests -t deploy`.
  - Upstream's `PooledWalReadersAndWriters_CanOpenConnectionsConcurrently` can fail with "database is locked" when the
    machine is busy (e.g. both suites at once). Run the suites one after the other; if it fails, rerun it alone and say so.
- Owner decisions this plan implements (spec section 1): scheme A (wire 8 = yellow knot for Available, 16 = white knot
  for Pending, 2 = blue knot for Finish; Lore, Lesson and None draw nothing); the 1.73 rule (a yellow knot only while
  `playerLevel - quest minimum level <= 15`); no level rule for daily, weekly and monthly quests nor for a scripted quest
  whose class doesn't declare `Level`; markers refresh by the quest effect alone (owner's check 2026-10-11: effect 8 drew
  the yellow knot on an NPC created without a flag, effect 0 cleared it).
- A rule for this and future code: `SendNPCsQuestEffect` always gets a **meaning** (the writer translates it); a raw
  wire value goes only through `QuestIndicators.SendRawEffect`.
- Out of scope (state it, don't build it): clients older than 1.124 (another create packet); white knots for scripted
  quests; the 15-level rule for Muirenn, bounty masters and faction emissaries (their classes keep their own rules).

## Review Focus

The inputs and conditions most likely to bite a player that unit tests can't reach (they need a live client), and the
check that pins each:

1. **A level change while standing among quest givers** (level-up, `/player level`): the markers must change at once.
   Pinned by `RefreshHookTests.test_the_level_setter` (Task 5) and in game (test guide, check 1).
2. **An NPC that comes back into range while the client still draws it** (it lingers on the client after leaving the
   server's range): its marker must follow the player's new state, even if the client takes the new create packet as an
   update. Pinned by `UT_IndicatorSentStore.ACreateThatChangesTheValueAsksARefreshThatSendsIt` (Task 2), the create
   check in `RulesAndPacketsTests` (Task 3) and in game (test guide, check 9).
3. **A refresh asked while the client is on a loading screen or not yet in the game** (zoning, login, a class change at
   load): nothing may be sent until the client is playing; the create packets on arrival carry the new values. Pinned by
   `RulesAndPacketsTests.test_the_refresh_runs_once_per_tick_for_a_playing_client_and_sends_what_the_writers_send`
   (Task 3).
4. **A GM's `/indicator create` value on an NPC, then a refresh**: the refresh must compare and record the same raw value
   the writers send, not the table's. Pinned by the same source check (`Run` asks `WireFor`, Task 3);
   `UT_IndicatorSentStore.ARawValueSentIsPutRight` (Task 2) covers the related case of a raw effect being put right.
5. **The daily rollover at midnight**: a daily's giver must light up again for players already standing there. Pinned by
   `RefreshHookTests.test_the_daily_weekly_and_monthly_rollovers` (Task 5) and `DailyWeeklyAndMonthlyQuestsHaveNoLevelRule`
   (Task 1).

Direct changes from one knot to another (8 to 16 to 2) are sent without a 0 between: the owner's `/indicator effect` run
of 2026-10-10 sent 1, 2, 4, 8 and 16 one after the other on Elaru and saw each drawn.

## Files

| File | Task | Responsibility |
|---|---|---|
| `source/server/GameServer/scripts/hearthdaoc/QuestIndicators.cs` (new) | 1, 2 | The rules (`For`), the table (`Wire`), raw values (`WireFor`, `SendRawEffect`); then `Sending`, `SendingCreate`, `Refresh` |
| `source/server/GameServer/scripts/hearthdaoc/IndicatorSentStore.cs` (new) | 2 | The wire value last sent per player and NPC; one queued refresh per player |
| `source/server/Tests/UnitTests/UT_QuestIndicators.cs` (new) | 1 | The rules, the table, the scripted and daily level rules |
| `source/server/Tests/UnitTests/UT_IndicatorSentStore.cs` (new) | 2 | The store and `SendChanges` |
| `.github/workflows/server-image.yml`, `deploy/tests/test_workflows.py` | 1, 2 | CI runs the two new test classes |
| `source/server/GameServer/gameobjects/GameNPC.cs` | 3 | `GetQuestIndicator` asks the rules |
| `source/server/GameServer/packets/Server/PacketLib1124.cs`, `PacketLib173.cs` | 3 | Meaning to wire, recorded |
| `deploy/tests/test_player_commands.py` | 3 | Its `GetQuestIndicator` slice follows the new code |
| `deploy/tests/test_quest_indicators.py` (new) | 3, 4, 5 | Source checks of every hook |
| `source/server/GameServer/scripts/hearthdaoc/QuestIndicatorProbe.cs`, `IndicatorCommand.cs`, `source/server/Tests/UnitTests/UT_QuestIndicatorProbe.cs` | 4 | `/indicator` follows the scheme; `effect` and `create` stay raw |
| `GamePlayer.cs`, `AbstractQuest.cs`, `DataQuest.cs`, `ECS-Services/{Daily,Weekly,Monthly}QuestService.cs`, `scripts/hearthdaoc/EpicCommand.cs` | 5 | The refresh hooks |
| `docs/fork/FORK.md`, `docs/fork/verification/sub4-test-guide.md` | 6 | The record and the owner's in-game checks |

---

### Task 1: The rules and the meaning-to-wire table

**Files:**
- Create: `source/server/GameServer/scripts/hearthdaoc/QuestIndicators.cs`
- Create: `source/server/Tests/UnitTests/UT_QuestIndicators.cs`
- Modify: `.github/workflows/server-image.yml` (the unit-test filter), `deploy/tests/test_workflows.py` (its pin)

**Interfaces:**
- Consumes (existing): `DataQuest.eStepType`, `QuestNames.Same(string, string)`, `IndicatorOverrides.TryGet(GamePlayer,
  GameNPC, out eQuestIndicator)` (from `QuestIndicatorProbe.cs`), `AbstractQuest`, `DataQuest`, `RewardQuest`,
  `Quests.DailyQuest`/`WeeklyQuest`/`MonthlyQuest` (in `DOL.GS.Quests`; the bare names clash with namespaces
  `DOL.GS.DailyQuest` etc., so write `Quests.DailyQuest`).
- Produces (namespace `DOL.GS.HearthDAoC`): `record struct JournalStep(DataQuest.eStepType Type, string TargetName,
  ushort TargetRegion)`; `record struct QuestOffer(int? MinLevel, bool Qualifies)`; `static class QuestIndicators` with
  `const int AvailableLevelSpan = 15`, `bool FinishesHere(DataQuest.eStepType)`, `bool PendsHere(DataQuest.eStepType)`,
  `bool Targets(JournalStep, string, ushort)`, `bool Shows(QuestOffer, int)`, `eQuestIndicator For(string npcName,
  ushort npcRegion, int playerLevel, IEnumerable<JournalStep> steps, bool rewardQuestDone, IEnumerable<QuestOffer>
  offers)`, `eQuestIndicator For(GameNPC, GamePlayer, AbstractQuest[] scripted, DataQuest[] offered)`,
  `int? ScriptedMinLevel(AbstractQuest)`, `eQuestIndicator Wire(eQuestIndicator meaning)`, `eQuestIndicator
  ToWire(eQuestIndicator value, bool raw)`, `eQuestIndicator WireFor(GamePlayer, GameNPC, eQuestIndicator)`,
  `void SendRawEffect(GamePlayer, GameNPC, byte)`.

- [ ] **Step 1: Write the failing tests.** Create `source/server/Tests/UnitTests/UT_QuestIndicators.cs` with exactly:

```csharp
using System;
using System.Collections.Generic;
using DOL.Events;
using DOL.GS.HearthDAoC;
using DOL.GS.Quests;
using NUnit.Framework;
using S = DOL.GS.Quests.DataQuest.eStepType;

namespace DOL.GS.Tests;

// HearthDAoC: the quest indicator rules and the meaning-to-wire table (spec
// docs/fork/specs/2026-10-11-quest-indicators-design.md, sections 2 and 3): turn in (blue), then the current step
// (white), then a quest to take (yellow) whose minimum level is at most 15 below the player's; and what the 1.127
// client gets for each meaning.
[TestFixture]
public sealed class UT_QuestIndicators
{
    private const ushort CaerGothwaite = 51;

    private static readonly JournalStep[] NoSteps = Array.Empty<JournalStep>();
    private static readonly QuestOffer[] NoOffers = Array.Empty<QuestOffer>();

    // Offers that fail the test when read: the journal decided first.
    private static IEnumerable<QuestOffer> Unread()
    {
        Assert.Fail("the offers were read");
        yield break;
    }

    private static eQuestIndicator At(string npc, int level, JournalStep[] steps = null, bool rewardDone = false,
        IEnumerable<QuestOffer> offers = null, ushort region = CaerGothwaite) =>
        QuestIndicators.For(npc, region, level, steps ?? NoSteps, rewardDone, offers ?? NoOffers);

    private static JournalStep Step(S type, string target, ushort region = CaerGothwaite) => new(type, target, region);

    [Test]
    public void AQuestToTakeIsAvailable()
    {
        // A new level-7 Infiltrator: Elaru offers "Strange Beings" (level 7).
        Assert.That(At("Elaru", 7, offers: new[] { new QuestOffer(7, true) }), Is.EqualTo(eQuestIndicator.Available));
        Assert.That(At("Elaru", 6, offers: new[] { new QuestOffer(7, false) }), Is.EqualTo(eQuestIndicator.None));
    }

    [TestCase(22, ExpectedResult = eQuestIndicator.Available)] // 15 levels above the quest's minimum
    [TestCase(23, ExpectedResult = eQuestIndicator.None)] // 16 above
    [TestCase(30, ExpectedResult = eQuestIndicator.None)] // the spec's level-30 passer-by
    public eQuestIndicator TheFifteenLevelRule(int playerLevel) =>
        At("Elaru", playerLevel, offers: new[] { new QuestOffer(7, true) });

    [Test]
    public void AQuestWithoutAMinimumLevelHasNoLevelRule()
    {
        Assert.That(At("Elaru", 50, offers: new[] { new QuestOffer(null, true) }), Is.EqualTo(eQuestIndicator.Available));
    }

    [Test]
    public void OneOfferInRangeIsEnough()
    {
        Assert.That(At("Elaru", 30, offers: new[] { new QuestOffer(7, true), new QuestOffer(20, true) }),
            Is.EqualTo(eQuestIndicator.Available));
    }

    [TestCase(S.Interact)]
    [TestCase(S.Whisper)]
    [TestCase(S.Deliver)]
    [TestCase(S.Collect)]
    public void ACurrentStepAtTheNpcIsPending(S type)
    {
        Assert.That(At("Tage", 7, new[] { Step(type, "Tage") }, offers: Unread()), Is.EqualTo(eQuestIndicator.Pending));
    }

    [TestCase(S.InteractFinish)]
    [TestCase(S.WhisperFinish)]
    [TestCase(S.DeliverFinish)]
    [TestCase(S.CollectFinish)]
    public void ALastStepAtTheNpcIsFinish(S type)
    {
        Assert.That(At("Adam Glaze", 9, new[] { Step(type, "Adam Glaze") }, offers: Unread()),
            Is.EqualTo(eQuestIndicator.Finish));
    }

    [TestCase(S.Kill)]
    [TestCase(S.KillFinish)]
    [TestCase(S.Search)]
    [TestCase(S.SearchFinish)]
    [TestCase(S.Unknown)]
    public void KillAndSearchTargetsGetNothing(S type)
    {
        // "Cleric Mulgrut" (level 5) ends on killing Mulgrut Maggot: no blue knot on the monster.
        Assert.That(At("Mulgrut Maggot", 5, new[] { Step(type, "Mulgrut Maggot", 1) }, region: 1),
            Is.EqualTo(eQuestIndicator.None));
    }

    [Test]
    public void ARewardQuestWithEveryGoalDoneIsFinish()
    {
        Assert.That(At("Bounty Master", 20, rewardDone: true, offers: Unread()), Is.EqualTo(eQuestIndicator.Finish));
    }

    [Test]
    public void FinishThenPendingThenAvailable()
    {
        var available = new[] { new QuestOffer(7, true) };
        Assert.That(At("Elaru", 9, new[] { Step(S.Interact, "Elaru"), Step(S.InteractFinish, "Elaru") }, offers: available),
            Is.EqualTo(eQuestIndicator.Finish));
        Assert.That(At("Elaru", 9, new[] { Step(S.InteractFinish, "Elaru"), Step(S.Interact, "Elaru") }, offers: available),
            Is.EqualTo(eQuestIndicator.Finish));
        Assert.That(At("Elaru", 9, new[] { Step(S.Interact, "Elaru") }, offers: available), Is.EqualTo(eQuestIndicator.Pending));
        Assert.That(At("Elaru", 9, new[] { Step(S.Kill, "Elaru") }, offers: available), Is.EqualTo(eQuestIndicator.Available));
    }

    [Test]
    public void StepsElsewhereDoNotCount()
    {
        Assert.That(At("Elaru", 9, new[] { Step(S.Interact, "Tage") }), Is.EqualTo(eQuestIndicator.None));
        Assert.That(At("Tage", 9, new[] { Step(S.Interact, "Tage", 1) }), Is.EqualTo(eQuestIndicator.None));
        Assert.That(At("Tage", 9, new[] { Step(S.Interact, "") }), Is.EqualTo(eQuestIndicator.None));
    }

    [Test]
    public void NamesCompareWithoutCaseAndRegionZeroIsAnyRegion()
    {
        Assert.That(At("Tage", 9, new[] { Step(S.Interact, "tage") }), Is.EqualTo(eQuestIndicator.Pending));
        Assert.That(At("Tage", 9, new[] { Step(S.Interact, "TAGE", 0) }), Is.EqualTo(eQuestIndicator.Pending));
        Assert.That(At("Tage", 9, new[] { Step(S.Interact, "Tage ") }), Is.EqualTo(eQuestIndicator.None));
    }

    [Test]
    public void TheTableGivesTheKnots()
    {
        Assert.Multiple(() =>
        {
            Assert.That(QuestIndicators.Wire(eQuestIndicator.Available), Is.EqualTo(eQuestIndicator.Lore)); // 8, yellow knot
            Assert.That(QuestIndicators.Wire(eQuestIndicator.Pending), Is.EqualTo(eQuestIndicator.Pending)); // 16, white knot
            Assert.That(QuestIndicators.Wire(eQuestIndicator.Finish), Is.EqualTo(eQuestIndicator.Finish)); // 2, blue knot
            Assert.That(QuestIndicators.Wire(eQuestIndicator.None), Is.EqualTo(eQuestIndicator.None));
            // Atlas master trainers and the buff merchant say "lore": nothing now.
            Assert.That(QuestIndicators.Wire(eQuestIndicator.Lore), Is.EqualTo(eQuestIndicator.None));
            Assert.That(QuestIndicators.Wire(eQuestIndicator.Lesson), Is.EqualTo(eQuestIndicator.None));
            Assert.That(QuestIndicators.Wire((eQuestIndicator)0x20), Is.EqualTo(eQuestIndicator.None));
        });
    }

    [Test]
    public void ARawValueGoesAsItIs()
    {
        for (int value = 0; value <= 255; value++)
        {
            var indicator = (eQuestIndicator)value;
            Assert.That(QuestIndicators.ToWire(indicator, raw: true), Is.EqualTo(indicator));
            Assert.That(QuestIndicators.ToWire(indicator, raw: false), Is.EqualTo(QuestIndicators.Wire(indicator)));
        }
    }

    // Scripted quests: Level counts as the minimum level only when the class declares it.
    private abstract class Stub : AbstractQuest
    {
        public override bool CheckQuestQualification(GamePlayer player) => true;
        public override void Notify(DOLEvent e, object sender, EventArgs args) { }
    }

    private sealed class NoLevel : Stub { }

    private class Level48 : Stub
    {
        public override int Level => 48;
    }

    private sealed class InheritsLevel : Level48 { }

    [Test]
    public void AScriptedQuestsLevelCountsOnlyWhenItsClassDeclaresOne()
    {
        Assert.Multiple(() =>
        {
            Assert.That(new NoLevel().Level, Is.EqualTo(1));
            Assert.That(QuestIndicators.ScriptedMinLevel(new NoLevel()), Is.Null);
            Assert.That(QuestIndicators.ScriptedMinLevel(new Level48()), Is.EqualTo(48));
            Assert.That(QuestIndicators.ScriptedMinLevel(new InheritsLevel()), Is.EqualTo(48));
        });
    }

    // Atlas's daily, weekly and monthly quests declare a Level (TeamBuildingAlb 1, PlayerKillWeeklyQuestAlb 1, ...) but
    // follow the player's level: no level rule (owner, 2026-10-11).
    private sealed class Daily : Quests.DailyQuest
    {
        public override string QuestPropertyKey { get; set; } = "test";
        public override int Level => 1;
        public override void LoadQuestParameters() { }
        public override void SaveQuestParameters() { }
        public override void Notify(DOLEvent e, object sender, EventArgs args) { }
    }

    private sealed class Weekly : Quests.WeeklyQuest
    {
        public override string QuestPropertyKey { get; set; } = "test";
        public override int Level => 1;
        public override void LoadQuestParameters() { }
        public override void SaveQuestParameters() { }
        public override void Notify(DOLEvent e, object sender, EventArgs args) { }
    }

    private sealed class Monthly : Quests.MonthlyQuest
    {
        public override string QuestPropertyKey { get; set; } = "test";
        public override int Level => 45;
        public override void LoadQuestParameters() { }
        public override void SaveQuestParameters() { }
        public override void Notify(DOLEvent e, object sender, EventArgs args) { }
    }

    [Test]
    public void DailyWeeklyAndMonthlyQuestsHaveNoLevelRule()
    {
        Assert.Multiple(() =>
        {
            Assert.That(QuestIndicators.ScriptedMinLevel(new Daily()), Is.Null);
            Assert.That(QuestIndicators.ScriptedMinLevel(new Weekly()), Is.Null);
            Assert.That(QuestIndicators.ScriptedMinLevel(new Monthly()), Is.Null);
            // So a level-50 player still sees a level-1 daily's giver lit.
            Assert.That(At("Hector", 50, offers: new[] { new QuestOffer(QuestIndicators.ScriptedMinLevel(new Daily()), true) }),
                Is.EqualTo(eQuestIndicator.Available));
        });
    }
}
```

- [ ] **Step 2: Run them to see them fail.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --filter "FullyQualifiedName~UT_QuestIndicators"`
Expected: the build fails with `error CS0246` naming `JournalStep` and `QuestOffer`.

- [ ] **Step 3: Write the rules.** Create `source/server/GameServer/scripts/hearthdaoc/QuestIndicators.cs` with exactly
(Task 2 adds the refresh at the end of the class; `using DOL.Events;` and `using DOL.Logging;` are for it, so keep them):

```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using DOL.Events;
using DOL.GS.Quests;
using DOL.Logging;

namespace DOL.GS.HearthDAoC;

// HearthDAoC: one quest indicator scheme for every NPC (docs/fork/specs/2026-10-11-quest-indicators-design.md).
// GameNPC.GetQuestIndicator returns a meaning (Available: a quest to take; Pending: see me for your current step;
// Finish: turn in; None), worked out by For. The two packet writers the 1.127 client uses turn the meaning into the
// value the client draws (Wire: yellow, white or blue knot) and record it per player and NPC (LastSent). Refresh,
// asked for whenever a player's level, class or quests change, sends the quest effect for every NPC the client has
// whose value changed, at most once per game-loop tick.

// The current step of a data quest in the player's journal: DataQuest.StepType, TargetName and TargetRegion (region 0
// is any region).
public readonly record struct JournalStep(DataQuest.eStepType Type, string TargetName, ushort TargetRegion);

// A quest the NPC gives. Qualifies: GameNPC.CanShowOneQuest's test for this one quest. MinLevel: a data quest's
// MinLevel, a scripted quest's Level when its class declares one, else null (no level rule).
public readonly record struct QuestOffer(int? MinLevel, bool Qualifies);

public static class QuestIndicators
{
    // The 1.73 rule: no yellow knot for a quest whose minimum level is more than this below the player's level.
    public const int AvailableLevelSpan = 15;

    public static bool FinishesHere(DataQuest.eStepType type) => type is DataQuest.eStepType.DeliverFinish
        or DataQuest.eStepType.InteractFinish or DataQuest.eStepType.WhisperFinish or DataQuest.eStepType.CollectFinish;

    public static bool PendsHere(DataQuest.eStepType type) => type is DataQuest.eStepType.Deliver
        or DataQuest.eStepType.Interact or DataQuest.eStepType.Whisper or DataQuest.eStepType.Collect;

    // As GameNPC.CanFinishOneQuest compares: the name without case (QuestNames.Same), region 0 or the NPC's.
    public static bool Targets(JournalStep step, string npcName, ushort npcRegion) =>
        !string.IsNullOrEmpty(step.TargetName) && QuestNames.Same(step.TargetName, npcName)
        && (step.TargetRegion == 0 || step.TargetRegion == npcRegion);

    public static bool Shows(QuestOffer offer, int playerLevel) =>
        offer.Qualifies && (offer.MinLevel is not int min || playerLevel - min <= AvailableLevelSpan);

    // The meaning (Finish, Pending, Available or None). offers is read only when nothing in the journal ends or pends
    // at the NPC, so a lazy sequence runs the qualification checks only when they decide.
    public static eQuestIndicator For(string npcName, ushort npcRegion, int playerLevel,
        IEnumerable<JournalStep> steps, bool rewardQuestDone, IEnumerable<QuestOffer> offers)
    {
        if (rewardQuestDone)
            return eQuestIndicator.Finish;
        bool pending = false;
        foreach (JournalStep step in steps)
        {
            if (!Targets(step, npcName, npcRegion))
                continue;
            if (FinishesHere(step.Type))
                return eQuestIndicator.Finish;
            pending |= PendsHere(step.Type);
        }
        if (pending)
            return eQuestIndicator.Pending;
        foreach (QuestOffer offer in offers)
        {
            if (Shows(offer, playerLevel))
                return eQuestIndicator.Available;
        }
        return eQuestIndicator.None;
    }

    // GameNPC.GetQuestIndicator's inputs from the running server. scripted and offered are the NPC's quest lists,
    // copied under its locks.
    public static eQuestIndicator For(GameNPC npc, GamePlayer player, AbstractQuest[] scripted, DataQuest[] offered)
    {
        var steps = new List<JournalStep>();
        bool rewardQuestDone = false;
        foreach (KeyValuePair<AbstractQuest, byte> pair in player.QuestList)
        {
            switch (pair.Key)
            {
                case DataQuest dataQuest when dataQuest.Step > 0:
                    steps.Add(new JournalStep(dataQuest.StepType, dataQuest.TargetName, dataQuest.TargetRegion));
                    break;
                case RewardQuest rewardQuest when rewardQuest.QuestGiver == npc && rewardQuest.Goals.All(g => g.IsAchieved):
                    rewardQuestDone = true;
                    break;
            }
        }
        return For(npc.Name, npc.CurrentRegionID, player.Level, steps, rewardQuestDone, Offers(player, scripted, offered));
    }

    // GameNPC.CanShowOneQuest's tests, one offer per quest, in its order.
    private static IEnumerable<QuestOffer> Offers(GamePlayer player, AbstractQuest[] scripted, DataQuest[] offered)
    {
        foreach (AbstractQuest quest in scripted)
        {
            Type type = quest.GetType();
            int doing = player.IsDoingQuest(type) != null ? 1 : 0;
            yield return new QuestOffer(ScriptedMinLevel(quest),
                quest.CheckQuestQualification(player) && player.HasFinishedQuest(type) + doing < quest.MaxQuestCount);
        }
        foreach (DataQuest quest in offered)
        {
            // ShowIndicator first, as upstream: a Collection quest's check reads the database.
            if (quest.ShowIndicator)
                yield return new QuestOffer(quest.Level, quest.CheckQuestQualification(player));
        }
    }

    // AbstractQuest.Level is 1 unless a quest sets it; ten level-50 epics (Viking_50, Church_50, ...) never do, so their
    // Level says nothing about their minimum level. Daily, weekly and monthly quests (Atlas's) have no level rule: their
    // goals and rewards follow the player's level, so their givers keep the knot at any level (owner, 2026-10-11).
    private static readonly ConcurrentDictionary<Type, bool> s_declaresLevel = new();

    public static int? ScriptedMinLevel(AbstractQuest quest) =>
        quest is Quests.DailyQuest or Quests.WeeklyQuest or Quests.MonthlyQuest ? null
        : s_declaresLevel.GetOrAdd(quest.GetType(),
            static type => type.GetProperty(nameof(AbstractQuest.Level))?.GetMethod?.DeclaringType != typeof(AbstractQuest))
            ? quest.Level
            : null;

    // The meaning-to-wire table: the value the 1.127 client gets for a meaning (owner's /indicator test 2026-10-10).
    public static eQuestIndicator Wire(eQuestIndicator meaning) => meaning switch
    {
        eQuestIndicator.Available => eQuestIndicator.Lore, // 8: yellow knot
        eQuestIndicator.Pending => eQuestIndicator.Pending, // 16: white knot
        eQuestIndicator.Finish => eQuestIndicator.Finish, // 2: blue knot
        _ => eQuestIndicator.None, // Lore, Lesson, None, anything else: nothing
    };

    // A raw value goes as it is, a meaning through the table.
    public static eQuestIndicator ToWire(eQuestIndicator value, bool raw) => raw ? value : Wire(value);

    // Set while SendRawEffect sends /indicator effect's byte.
    [ThreadStatic]
    private static bool t_raw;

    // The value a packet writer puts on the wire for this player and NPC. /indicator's values stay raw: the byte of
    // /indicator effect (SendRawEffect), and the /indicator create value the GM set on this NPC, which
    // GameNPC.GetQuestIndicator returns (a class that ignores it gives its own value, which goes through the table).
    public static eQuestIndicator WireFor(GamePlayer player, GameNPC npc, eQuestIndicator value) =>
        ToWire(value, t_raw || (IndicatorOverrides.TryGet(player, npc, out eQuestIndicator forced) && forced == value));

    // /indicator effect: the quest effect with this byte, past the table.
    public static void SendRawEffect(GamePlayer player, GameNPC npc, byte value)
    {
        t_raw = true;
        try
        {
            player.Out.SendNPCsQuestEffect(npc, (eQuestIndicator)value);
        }
        finally
        {
            t_raw = false;
        }
    }
}
```

- [ ] **Step 4: Run the tests.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --filter "FullyQualifiedName~UT_QuestIndicators"`
Expected: `Passed!` with `Failed: 0` and `Passed: 27`.

- [ ] **Step 5: CI runs the new class.** CI's filter lists the fork's test classes by name and `test_workflows.py` pins
the list:

```bash
python3 /tmp/hdc-edit.py .github/workflows/server-image.yml <<'EDIT'
<<<<<<< OLD
          dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_CommandPrivLevelOverrides|FullyQualifiedName~UT_SiStartChoice|FullyQualifiedName~UT_ClassicBattlegrounds|FullyQualifiedName~UT_DataQuestDependency|FullyQualifiedName~UT_DataQuestDeliveryItem|FullyQualifiedName~UT_DataQuestOffers|FullyQualifiedName~UT_QuestNames|FullyQualifiedName~UT_ClassicQuestsExtra|FullyQualifiedName~UT_EpicChain|FullyQualifiedName~UT_QuestIndicatorProbe"
=======
          dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_CommandPrivLevelOverrides|FullyQualifiedName~UT_SiStartChoice|FullyQualifiedName~UT_ClassicBattlegrounds|FullyQualifiedName~UT_DataQuestDependency|FullyQualifiedName~UT_DataQuestDeliveryItem|FullyQualifiedName~UT_DataQuestOffers|FullyQualifiedName~UT_QuestNames|FullyQualifiedName~UT_ClassicQuestsExtra|FullyQualifiedName~UT_EpicChain|FullyQualifiedName~UT_QuestIndicatorProbe|FullyQualifiedName~UT_QuestIndicators"
>>>>>>> NEW
EDIT
```
```bash
python3 /tmp/hdc-edit.py deploy/tests/test_workflows.py <<'EDIT'
<<<<<<< OLD
                     '|FullyQualifiedName~UT_QuestIndicatorProbe"')
=======
                     '|FullyQualifiedName~UT_QuestIndicatorProbe'
                     '|FullyQualifiedName~UT_QuestIndicators"')
>>>>>>> NEW
<<<<<<< OLD
                                 "UT_QuestIndicatorProbe"])
=======
                                 "UT_QuestIndicatorProbe",
                                 "UT_QuestIndicators"])
>>>>>>> NEW
EDIT
```

Run: `python3 -B -m unittest deploy/tests/test_workflows.py`
Expected: `OK`.

- [ ] **Step 6: Commit.**

```bash
git add source/server/GameServer/scripts/hearthdaoc/QuestIndicators.cs source/server/Tests/UnitTests/UT_QuestIndicators.cs .github/workflows/server-image.yml deploy/tests/test_workflows.py
git commit -m "feat(indicators): the quest indicator rules and the meaning-to-wire table

One set of rules for every NPC: turn in (blue knot), then the current step
(white), then a quest to take (yellow) whose minimum level is at most 15
below the player's; daily, weekly and monthly quests have no level rule.
The table turns a meaning into the value the 1.127 client draws.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: What each client was sent, and the refresh

**Files:**
- Create: `source/server/GameServer/scripts/hearthdaoc/IndicatorSentStore.cs`
- Create: `source/server/Tests/UnitTests/UT_IndicatorSentStore.cs`
- Modify: `source/server/GameServer/scripts/hearthdaoc/QuestIndicators.cs` (append the refresh to the class)
- Modify: `.github/workflows/server-image.yml`, `deploy/tests/test_workflows.py`

**Interfaces:**
- Consumes: Task 1's `QuestIndicators.Wire`, `WireFor`; upstream's `GameLoopService.Instance.Post(Action<T>, T)`,
  `GamePlayer.PlayerObjectCache` (`NpcUpdateCache`, `NpcUpdateCacheLock`), `GamePlayerEvent.Quit`, `GameEventMgr`.
- Produces: `sealed class IndicatorSentStore` with `byte Last(object player, object npc)`, `void Record(object player,
  object npc, byte wire)`, `int Count(object player)`, `bool TryQueue(object player)`, `bool Dequeue(object player)`,
  `void Prune(object player, Func<object, bool> gone)`, `void Forget(object player)`, `int SendChanges(object player,
  IEnumerable<object> known, Func<object, (eQuestIndicator Meaning, byte Wire)> valueOf, Action<object, eQuestIndicator>
  send)`, `const byte Unknown = 0xFF`, `bool RecordCreate(object player, object npc, byte wire)`; in `QuestIndicators`:
  `static readonly IndicatorSentStore LastSent`, `eQuestIndicator Sending(GamePlayer, GameNPC, eQuestIndicator)` (the
  quest effect's writer, Task 3), `eQuestIndicator SendingCreate(GamePlayer, GameNPC, eQuestIndicator)` (the create
  packet's writer, Task 3), `void Refresh(GamePlayer)` (Task 5's hooks call it).

- [ ] **Step 1: Write the failing tests.** Create `source/server/Tests/UnitTests/UT_IndicatorSentStore.cs` with exactly:

```csharp
using System;
using System.Collections.Generic;
using DOL.GS.HearthDAoC;
using NUnit.Framework;

namespace DOL.GS.Tests;

// HearthDAoC: keeping quest markers current (spec docs/fork/specs/2026-10-11-quest-indicators-design.md, section 3.3):
// the wire value last sent per (player, NPC), one queued refresh per player however often it is asked, and a refresh
// that sends only what changed.
[TestFixture]
public sealed class UT_IndicatorSentStore
{
    // A refresh over the NPCs the client has, with these meanings; what it sends is added to sent.
    private static int Refresh(IndicatorSentStore store, object player, object[] known,
        Dictionary<object, eQuestIndicator> meaning, List<(object, eQuestIndicator)> sent) =>
        store.SendChanges(player, known, npc => (meaning[npc], (byte)QuestIndicators.Wire(meaning[npc])),
            (npc, m) => sent.Add((npc, m)));

    [Test]
    public void NothingSentReadsAsNothing()
    {
        var store = new IndicatorSentStore();
        Assert.That(store.Last(new object(), new object()), Is.EqualTo(0));
    }

    [Test]
    public void ZeroIsNotKept()
    {
        var store = new IndicatorSentStore();
        object player = new(), elaru = new();
        store.Record(player, elaru, 8);
        Assert.That(store.Count(player), Is.EqualTo(1));
        store.Record(player, elaru, 0);
        Assert.That(store.Count(player), Is.EqualTo(0));
        Assert.That(store.Last(player, elaru), Is.EqualTo(0));
    }

    [Test]
    public void OnlyChangedValuesAreSent()
    {
        var store = new IndicatorSentStore();
        object player = new(), elaru = new(), tage = new(), maggot = new();
        object[] known = { elaru, tage, maggot };
        var meaning = new Dictionary<object, eQuestIndicator>
        {
            [elaru] = eQuestIndicator.Available, [tage] = eQuestIndicator.None, [maggot] = eQuestIndicator.None,
        };
        var sent = new List<(object, eQuestIndicator)>();
        store.Record(player, elaru, 8); // Elaru's create packet carried the yellow knot.
        Assert.That(Refresh(store, player, known, meaning, sent), Is.EqualTo(0));

        // "Strange Beings" accepted: Elaru's knot goes, Tage's white knot comes.
        meaning[elaru] = eQuestIndicator.None;
        meaning[tage] = eQuestIndicator.Pending;
        Assert.That(Refresh(store, player, known, meaning, sent), Is.EqualTo(2));
        Assert.That(sent, Is.EqualTo(new[] { (elaru, eQuestIndicator.None), (tage, eQuestIndicator.Pending) }));
        Assert.That(store.Last(player, tage), Is.EqualTo(16));
        Assert.That(Refresh(store, player, known, meaning, sent), Is.EqualTo(0));
    }

    [Test]
    public void LoreAndLessonAreNothingSoNotSent()
    {
        var store = new IndicatorSentStore();
        object player = new(), trainer = new(), merchant = new();
        var meaning = new Dictionary<object, eQuestIndicator>
        {
            [trainer] = eQuestIndicator.Lore, [merchant] = eQuestIndicator.Lesson,
        };
        var sent = new List<(object, eQuestIndicator)>();
        Assert.That(Refresh(store, player, new[] { trainer, merchant }, meaning, sent), Is.EqualTo(0));
    }

    [Test]
    public void ARawValueSentIsPutRight()
    {
        // /indicator effect 1 drew the ring; the next refresh sends the real value (8, the yellow knot).
        var store = new IndicatorSentStore();
        object gm = new(), elaru = new();
        store.Record(gm, elaru, 1);
        var sent = new List<(object, eQuestIndicator)>();
        var meaning = new Dictionary<object, eQuestIndicator> { [elaru] = eQuestIndicator.Available };
        Assert.That(Refresh(store, gm, new[] { elaru }, meaning, sent), Is.EqualTo(1));
        Assert.That(store.Last(gm, elaru), Is.EqualTo(8));
    }

    [Test]
    public void ACreateThatChangesTheValueAsksARefreshThatSendsIt()
    {
        // Elaru lingered on the client with a yellow knot; she comes back into range with nothing for the player now.
        var store = new IndicatorSentStore();
        object player = new(), elaru = new();
        store.Record(player, elaru, 8);
        Assert.That(store.RecordCreate(player, elaru, 0), Is.True);
        Assert.That(store.Last(player, elaru), Is.EqualTo(IndicatorSentStore.Unknown));
        var sent = new List<(object, eQuestIndicator)>();
        var meaning = new Dictionary<object, eQuestIndicator> { [elaru] = eQuestIndicator.None };
        Assert.That(Refresh(store, player, new[] { elaru }, meaning, sent), Is.EqualTo(1));
        Assert.That(sent, Is.EqualTo(new[] { (elaru, eQuestIndicator.None) }));
        Assert.That(store.Last(player, elaru), Is.EqualTo(0));
    }

    [Test]
    public void ACreateWithTheSameValueAsksNothing()
    {
        var store = new IndicatorSentStore();
        object player = new(), tage = new(), guard = new();
        store.Record(player, tage, 16);
        Assert.That(store.RecordCreate(player, tage, 16), Is.False);
        Assert.That(store.RecordCreate(player, guard, 0), Is.False);
        Assert.That(store.Last(player, tage), Is.EqualTo(16));
    }

    [Test]
    public void AFirstCreateWithAMarkerIsSentAgainByTheRefresh()
    {
        var store = new IndicatorSentStore();
        object player = new(), elaru = new();
        Assert.That(store.RecordCreate(player, elaru, 8), Is.True);
        var sent = new List<(object, eQuestIndicator)>();
        var meaning = new Dictionary<object, eQuestIndicator> { [elaru] = eQuestIndicator.Available };
        Assert.That(Refresh(store, player, new[] { elaru }, meaning, sent), Is.EqualTo(1));
        Assert.That(store.Last(player, elaru), Is.EqualTo(8));
    }

    [Test]
    public void SeveralRequestsQueueOneRun()
    {
        var store = new IndicatorSentStore();
        object player = new();
        Assert.That(store.TryQueue(player), Is.True);
        Assert.That(store.TryQueue(player), Is.False);
        Assert.That(store.TryQueue(player), Is.False);
        Assert.That(store.Dequeue(player), Is.True);
        Assert.That(store.TryQueue(player), Is.True); // asked again during or after the run: the next tick's run
    }

    [Test]
    public void AnEmptyCacheSendsNothing()
    {
        var store = new IndicatorSentStore();
        object player = new();
        store.Record(player, new object(), 8);
        int count = store.SendChanges(player, Array.Empty<object>(), _ => (eQuestIndicator.Finish, (byte)2),
            (_, _) => Assert.Fail("sent with nothing on the client"));
        Assert.That(count, Is.EqualTo(0));
    }

    [Test]
    public void PlayersAreSeparate()
    {
        var store = new IndicatorSentStore();
        object one = new(), two = new(), elaru = new();
        store.Record(one, elaru, 8);
        Assert.That(store.Last(two, elaru), Is.EqualTo(0));
        Assert.That(store.TryQueue(one), Is.True);
        Assert.That(store.TryQueue(two), Is.True);
    }

    [Test]
    public void PruneDropsWhatIsGone()
    {
        var store = new IndicatorSentStore();
        object player = new(), elaru = new(), dead = new();
        store.Record(player, elaru, 8);
        store.Record(player, dead, 2);
        store.Prune(player, npc => ReferenceEquals(npc, dead));
        Assert.That(store.Last(player, elaru), Is.EqualTo(8));
        Assert.That(store.Last(player, dead), Is.EqualTo(0));
    }

    [Test]
    public void ForgetDropsThePlayerAndItsQueue()
    {
        var store = new IndicatorSentStore();
        object player = new(), elaru = new();
        store.Record(player, elaru, 2);
        Assert.That(store.TryQueue(player), Is.True);
        store.Forget(player);
        Assert.That(store.Last(player, elaru), Is.EqualTo(0));
        Assert.That(store.Dequeue(player), Is.False); // the posted run finds the player gone
    }
}
```

- [ ] **Step 2: Run them to see them fail.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --filter "FullyQualifiedName~UT_IndicatorSentStore"`
Expected: the build fails with `error CS0246` naming `IndicatorSentStore`.

- [ ] **Step 3: Write the store.** Create `source/server/GameServer/scripts/hearthdaoc/IndicatorSentStore.cs` with exactly:

```csharp
using System;
using System.Collections.Generic;
using System.Runtime.CompilerServices;
using System.Threading;

namespace DOL.GS.HearthDAoC;

// HearthDAoC: part of the quest indicators (QuestIndicators.cs; spec docs/fork/specs/2026-10-11-quest-indicators-design.md,
// section 3.3).

// The wire value each player's client was last sent for each NPC, by the create packet's flags or the quest effect,
// and whether a refresh is queued for the player. Players and NPCs compare by reference; a player's values go with the
// player object, and at its Quit. No value means 0 (nothing drawn), so only NPCs that show a marker take room. It reads
// nothing from the running server, so unit tests drive it with plain objects.
public sealed class IndicatorSentStore
{
    private sealed class PlayerSent
    {
        // A leaf lock: held only around Wire.
        public readonly Lock Lock = new();
        public readonly Dictionary<object, byte> Wire = new(ReferenceEqualityComparer.Instance);
        public int Queued;
    }

    private readonly ConditionalWeakTable<object, PlayerSent> _players = new();

    private PlayerSent For(object player) => _players.GetValue(player, static _ => new PlayerSent());

    // The wire value last sent to the player's client for the NPC; 0 if none.
    public byte Last(object player, object npc)
    {
        if (!_players.TryGetValue(player, out PlayerSent sent))
            return 0;
        lock (sent.Lock)
            return sent.Wire.TryGetValue(npc, out byte wire) ? wire : (byte)0;
    }

    // A value no client draws: "unknown", so the next refresh sends the real one.
    public const byte Unknown = 0xFF;

    // What a writer just sent to the player's client for the NPC.
    public void Record(object player, object npc, byte wire)
    {
        PlayerSent sent;
        if (wire != 0)
            sent = For(player);
        else if (!_players.TryGetValue(player, out sent))
            return;
        lock (sent.Lock)
        {
            if (wire == 0)
                sent.Wire.Remove(npc);
            else
                sent.Wire[npc] = wire;
        }
    }

    // What a create packet just carried. A client that still has the NPC (out of the server's range it lingers on the
    // client) may take the create as an update and keep its old drawing; so a value that differs from the last one sent
    // is recorded as Unknown, and the caller asks a refresh, whose quest effect draws it. True when that refresh is needed.
    public bool RecordCreate(object player, object npc, byte wire)
    {
        PlayerSent sent = For(player);
        lock (sent.Lock)
        {
            byte last = sent.Wire.TryGetValue(npc, out byte value) ? value : (byte)0;
            if (last == wire)
                return false;
            sent.Wire[npc] = Unknown;
            return true;
        }
    }

    // How many NPCs hold a value for the player.
    public int Count(object player)
    {
        if (!_players.TryGetValue(player, out PlayerSent sent))
            return 0;
        lock (sent.Lock)
            return sent.Wire.Count;
    }

    // True when this call queued the player's refresh, so the caller posts it; false when one is already queued.
    public bool TryQueue(object player) => Interlocked.Exchange(ref For(player).Queued, 1) == 0;

    // The queued refresh starts: a request from now on queues the next one. False when the player is gone (Forget).
    public bool Dequeue(object player)
    {
        if (!_players.TryGetValue(player, out PlayerSent sent))
            return false;
        Interlocked.Exchange(ref sent.Queued, 0);
        return true;
    }

    // Drops the values of NPCs the player's client can no longer have. gone runs under the leaf lock, so it must only
    // read plain fields.
    public void Prune(object player, Func<object, bool> gone)
    {
        if (!_players.TryGetValue(player, out PlayerSent sent))
            return;
        lock (sent.Lock)
        {
            List<object> drop = null;
            foreach (object npc in sent.Wire.Keys)
            {
                if (gone(npc))
                    (drop ??= new List<object>()).Add(npc);
            }
            if (drop == null)
                return;
            foreach (object npc in drop)
                sent.Wire.Remove(npc);
        }
    }

    // The player has quit.
    public void Forget(object player) => _players.Remove(player);

    // One refresh: for each NPC the player's client has (known), its meaning and wire value now (valueOf); sends the
    // meaning where the wire value differs from the last one sent (the writer turns it into that value), and records
    // it. Returns how many it sent.
    public int SendChanges(object player, IEnumerable<object> known,
        Func<object, (eQuestIndicator Meaning, byte Wire)> valueOf, Action<object, eQuestIndicator> send)
    {
        int count = 0;
        foreach (object npc in known)
        {
            (eQuestIndicator meaning, byte wire) = valueOf(npc);
            if (wire == Last(player, npc))
                continue;
            send(npc, meaning);
            Record(player, npc, wire);
            count++;
        }
        return count;
    }
}
```

- [ ] **Step 4: Add the refresh to `QuestIndicators`** (the end of the class, after `SendRawEffect`). `Run` copies the
client's NPC list under ClientService's lock and asks each NPC with no lock held (one NPC's exception is logged and
leaves its marker as it was); `GameLoopService` runs posted actions at the start of each tick, before ClientService
sends the clients' packets. `SendingCreate` is for the create packet: a value that differs from the last one sent is
recorded as unknown and asks a refresh, because a client that still had the NPC (out of the server's range it lingers on
the client) may take the create as an update and keep its old drawing; the refresh's quest effect draws it.

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/scripts/hearthdaoc/QuestIndicators.cs <<'EDIT'
<<<<<<< OLD
            t_raw = false;
        }
    }
}
=======
            t_raw = false;
        }
    }

    public static readonly IndicatorSentStore LastSent = new();

    private static readonly Logger Log = LoggerManager.Create(typeof(QuestIndicators));

    // Called by the quest effect's writer (PacketLib173.SendNPCsQuestEffect) with the value it was given: returns the
    // value to send, recorded as the last one sent to the player for the NPC.
    public static eQuestIndicator Sending(GamePlayer player, GameNPC npc, eQuestIndicator value)
    {
        eQuestIndicator wire = WireFor(player, npc, value);
        LastSent.Record(player, npc, (byte)wire);
        return wire;
    }

    // Called by the create packet's writer (PacketLib1124.SendNPCCreate): as Sending, but a value that differs from the
    // last one sent also asks a refresh, whose quest effect draws it even on a client that still had the NPC.
    public static eQuestIndicator SendingCreate(GamePlayer player, GameNPC npc, eQuestIndicator value)
    {
        eQuestIndicator wire = WireFor(player, npc, value);
        if (LastSent.RecordCreate(player, npc, (byte)wire))
            Refresh(player);
        return wire;
    }

    private static readonly Action<GamePlayer> s_run = Run;

    // Asks for the markers of every NPC the player's client has to be worked out again. Safe from any thread and under
    // any lock; it only queues. However often it is asked between two game-loop ticks, the work runs once, at the start
    // of the next tick (GameLoopService's posted actions, which run before ClientService sends the clients' packets),
    // after the change that asked is complete. Posted actions run in parallel with each other; that is safe here (packet
    // queues take concurrent senders, and only leaf locks are held), as long as no quest change itself runs as a
    // GameLoopService posted action (none does), since a run in the same batch could read a half-finished change.
    public static void Refresh(GamePlayer player)
    {
        if (player != null && LastSent.TryQueue(player))
            GameLoopService.Instance.Post(s_run, player);
    }

    private static void Run(GamePlayer player)
    {
        if (!LastSent.Dequeue(player))
            return;
        // Not in the world or not playing (login, a region change's loading screen, link death): once in, the client
        // gets every NPC again with its create packet.
        if (player.ObjectState != GameObject.eObjectState.Active
            || player.Client?.ClientState != GameClient.eClientState.Playing)
            return;

        // The NPCs the client has (ClientService's cache), copied under its lock; the NPCs are asked with no lock held.
        PlayerObjectCache cache = player.PlayerObjectCache;
        List<GameNPC> known;
        lock (cache.NpcUpdateCacheLock)
            known = new List<GameNPC>(cache.NpcUpdateCache.Keys);

        // An NPC out of the world or in another region is off the client (and its object ID may be reused).
        ushort region = player.CurrentRegionID;
        LastSent.Prune(player, o => o is not GameNPC npc || npc.ObjectState != GameObject.eObjectState.Active
            || npc.CurrentRegionID != region);
        known.RemoveAll(npc => npc.ObjectState != GameObject.eObjectState.Active || npc.CurrentRegionID != region);

        LastSent.SendChanges(player, known, o =>
            {
                GameNPC npc = (GameNPC)o;
                try
                {
                    eQuestIndicator meaning = npc.GetQuestIndicator(player);
                    return (meaning, (byte)WireFor(player, npc, meaning));
                }
                catch (Exception e)
                {
                    // One NPC's failure must not stop the others' markers: it keeps what it had.
                    Log.Error($"Quest indicator of {npc.Name} for {player.Name}", e);
                    return (eQuestIndicator.None, LastSent.Last(player, npc));
                }
            },
            (o, meaning) => player.Out.SendNPCsQuestEffect((GameNPC)o, meaning));
    }

    [ScriptLoadedEvent]
    public static void OnScriptLoaded(DOLEvent e, object sender, EventArgs args) =>
        GameEventMgr.AddHandler(GamePlayerEvent.Quit, OnPlayerQuit);

    [ScriptUnloadedEvent]
    public static void OnScriptUnloaded(DOLEvent e, object sender, EventArgs args) =>
        GameEventMgr.RemoveHandler(GamePlayerEvent.Quit, OnPlayerQuit);

    private static void OnPlayerQuit(DOLEvent e, object sender, EventArgs args)
    {
        if (sender is GamePlayer player)
            LastSent.Forget(player);
    }
}
>>>>>>> NEW
EDIT
```

- [ ] **Step 5: Run the tests.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --filter "FullyQualifiedName~UT_IndicatorSentStore|FullyQualifiedName~UT_QuestIndicators"`
Expected: `Passed!` with `Failed: 0` and `Passed: 40`.

- [ ] **Step 6: CI runs the new class.**

```bash
python3 /tmp/hdc-edit.py .github/workflows/server-image.yml <<'EDIT'
<<<<<<< OLD
          dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_CommandPrivLevelOverrides|FullyQualifiedName~UT_SiStartChoice|FullyQualifiedName~UT_ClassicBattlegrounds|FullyQualifiedName~UT_DataQuestDependency|FullyQualifiedName~UT_DataQuestDeliveryItem|FullyQualifiedName~UT_DataQuestOffers|FullyQualifiedName~UT_QuestNames|FullyQualifiedName~UT_ClassicQuestsExtra|FullyQualifiedName~UT_EpicChain|FullyQualifiedName~UT_QuestIndicatorProbe|FullyQualifiedName~UT_QuestIndicators"
=======
          dotnet test source/server/Tests/Tests.csproj --nologo --filter "FullyQualifiedName~UT_CommandPrivLevelOverrides|FullyQualifiedName~UT_SiStartChoice|FullyQualifiedName~UT_ClassicBattlegrounds|FullyQualifiedName~UT_DataQuestDependency|FullyQualifiedName~UT_DataQuestDeliveryItem|FullyQualifiedName~UT_DataQuestOffers|FullyQualifiedName~UT_QuestNames|FullyQualifiedName~UT_ClassicQuestsExtra|FullyQualifiedName~UT_EpicChain|FullyQualifiedName~UT_QuestIndicatorProbe|FullyQualifiedName~UT_QuestIndicators|FullyQualifiedName~UT_IndicatorSentStore"
>>>>>>> NEW
EDIT
```
```bash
python3 /tmp/hdc-edit.py deploy/tests/test_workflows.py <<'EDIT'
<<<<<<< OLD
                     '|FullyQualifiedName~UT_QuestIndicators"')
=======
                     '|FullyQualifiedName~UT_QuestIndicators|FullyQualifiedName~UT_IndicatorSentStore"')
>>>>>>> NEW
<<<<<<< OLD
                                 "UT_QuestIndicators"])
=======
                                 "UT_QuestIndicators", "UT_IndicatorSentStore"])
>>>>>>> NEW
EDIT
```

Run: `python3 -B -m unittest deploy/tests/test_workflows.py`
Expected: `OK`.

- [ ] **Step 7: Commit.**

```bash
git add source/server/GameServer/scripts/hearthdaoc/IndicatorSentStore.cs source/server/GameServer/scripts/hearthdaoc/QuestIndicators.cs source/server/Tests/UnitTests/UT_IndicatorSentStore.cs .github/workflows/server-image.yml deploy/tests/test_workflows.py
git commit -m "feat(indicators): remember what each client was sent, and refresh only what changed

The store keeps the wire value last sent per player and NPC and one queued
refresh per player. Refresh runs once per game-loop tick, as a posted action
of GameLoopService, and sends the quest effect only where a value changed.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: NPCs and both packets use the scheme

**Files:**
- Create: `deploy/tests/test_quest_indicators.py`
- Modify: `source/server/GameServer/gameobjects/GameNPC.cs` (`GetQuestIndicator`, after the existing `/indicator` block)
- Modify: `source/server/GameServer/packets/Server/PacketLib1124.cs` (`SendNPCCreate`), `PacketLib173.cs`
  (`SendNPCsQuestEffect`)
- Modify: `deploy/tests/test_player_commands.py` (line 73 slices `GetQuestIndicator` up to the old rules)

**Interfaces:**
- Consumes: `QuestIndicators.For(GameNPC, GamePlayer, AbstractQuest[], DataQuest[])` (Task 1),
  `QuestIndicators.SendingCreate` and `QuestIndicators.Sending(GamePlayer, GameNPC, eQuestIndicator)` (Task 2); `GameNPC`'s `_questListToGiveLock`,
  `m_questListToGive`, `_dataQuestsLock`, `DataQuestList` (each list is copied under its own lock, not nested).
- Produces: `GameNPC.GetQuestIndicator` returns a meaning; every create packet and quest effect carries the scheme's
  wire value, recorded in `QuestIndicators.LastSent`.

- [ ] **Step 1: Write the failing source checks.** Create `deploy/tests/test_quest_indicators.py` with exactly (Tasks 4
and 5 add two more classes):

```python
"""Quest indicators: one scheme for every quest, kept current (source checks).

Spec docs/fork/specs/2026-10-11-quest-indicators-design.md. GameNPC.GetQuestIndicator returns a meaning worked out by
QuestIndicators.For; the two packet writers the 1.127 client uses (PacketLib1124.SendNPCCreate, PacketLib173.
SendNPCsQuestEffect) turn it into the value the client draws and record it; a change of level, class or quests, and the
daily, weekly and monthly rollovers, ask QuestIndicators.Refresh, which sends the quest effect where a value changed.
The rules, the table and the refresh's store are unit-tested (UT_QuestIndicators, UT_IndicatorSentStore); the hooks in
upstream files need a live server, client and region, so these check the source.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GAME_SERVER = os.path.join(ROOT, "source", "server", "GameServer")
FORK = os.path.join(GAME_SERVER, "scripts", "hearthdaoc")
GAME_NPC = os.path.join(GAME_SERVER, "gameobjects", "GameNPC.cs")
GAME_PLAYER = os.path.join(GAME_SERVER, "gameobjects", "GamePlayer.cs")
CREATE = os.path.join(GAME_SERVER, "packets", "Server", "PacketLib1124.cs")
EFFECT = os.path.join(GAME_SERVER, "packets", "Server", "PacketLib173.cs")
ABSTRACT_QUEST = os.path.join(GAME_SERVER, "quests", "QuestsMgr", "AbstractQuest.cs")
DATA_QUEST = os.path.join(GAME_SERVER, "quests", "QuestsMgr", "DataQuest.cs")
DAILY = os.path.join(GAME_SERVER, "ECS-Services", "DailyQuestService.cs")
WEEKLY = os.path.join(GAME_SERVER, "ECS-Services", "WeeklyQuestService.cs")
MONTHLY = os.path.join(GAME_SERVER, "ECS-Services", "MonthlyQuestService.cs")
QUEST_INDICATORS = os.path.join(FORK, "QuestIndicators.cs")
SENT_STORE = os.path.join(FORK, "IndicatorSentStore.cs")
EPIC = os.path.join(FORK, "EpicCommand.cs")
INDICATOR = os.path.join(FORK, "IndicatorCommand.cs")


def read(path):
    """A C# source file's text (upstream files may start with a BOM; a few are not UTF-8)."""
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        return f.read()


def between(text, start, end):
    """The text from the first start up to the first end after it."""
    body = text[text.index(start):]
    return body[:body.index(end)]


def marked(test, body, call):
    """The body calls the fork once, on a line marked // HearthDAoC: (the line itself or the comment line above)."""
    test.assertEqual(body.count(call), 1, call)
    line = body[:body.index(call)].rsplit("\n", 2)
    test.assertIn("HearthDAoC:", "\n".join(line[-2:]) + body[body.index(call):].split("\n", 1)[0], call)


class RulesAndPacketsTests(unittest.TestCase):
    def test_get_quest_indicator_asks_the_gm_value_then_the_rules(self):
        body = between(read(GAME_NPC), "public virtual eQuestIndicator GetQuestIndicator(GamePlayer player)",
                       "\n\t\t}\n")
        override = body.index("HearthDAoC.IndicatorOverrides.TryGet(player, this, out eQuestIndicator forced)")
        rules = body.index("return HearthDAoC.QuestIndicators.For(this, player, scripted, offered);")
        self.assertLess(override, rules)
        self.assertIn("// HearthDAoC: one set of rules for every NPC", body)
        self.assertNotIn("CanShowOneQuest(player)", body)
        self.assertNotIn("CanFinishOneQuest(player)", body)

    def test_the_create_packet_sends_the_wire_value(self):
        body = between(read(CREATE), "public override void SendNPCCreate(GameNPC npc)", "pak.WriteByte(flags3);")
        asked = body.index("eQuestIndicator questIndicator = npc.GetQuestIndicator(m_gameClient.Player);")
        mapped = body.index("questIndicator = HearthDAoC.QuestIndicators.SendingCreate(m_gameClient.Player, npc, questIndicator);")
        first_flag = body.index("if (questIndicator == eQuestIndicator.Available)")
        self.assertLess(asked, mapped)
        self.assertLess(mapped, first_flag)
        marked(self, body, "HearthDAoC.QuestIndicators.SendingCreate(")

    def test_the_quest_effect_sends_the_wire_value(self):
        body = between(read(EFFECT), "public override void SendNPCsQuestEffect(GameNPC npc, eQuestIndicator indicator)",
                       "SendTCP(pak);")
        mapped = body.index("indicator = HearthDAoC.QuestIndicators.Sending(m_gameClient.Player, npc, indicator);")
        self.assertLess(body.index("if (m_gameClient.Player == null || npc == null)"), mapped)
        self.assertLess(mapped, body.index("pak.WriteByte((byte)indicator);"))
        marked(self, body, "HearthDAoC.QuestIndicators.Sending(")

    def test_the_refresh_runs_once_per_tick_for_a_playing_client_and_sends_what_the_writers_send(self):
        text = read(QUEST_INDICATORS)
        refresh = between(text, "public static void Refresh(GamePlayer player)", "\n    }\n")
        self.assertIn("LastSent.TryQueue(player)", refresh)
        self.assertIn("GameLoopService.Instance.Post(s_run, player);", refresh)
        run = between(text, "private static void Run(GamePlayer player)", "\n    }\n")
        # A client on a loading screen or not yet in the game gets every NPC again with its create packet.
        self.assertIn("player.Client?.ClientState != GameClient.eClientState.Playing", run)
        # The NPCs are asked with the cache lock released, and through the writers' own WireFor (a GM's /indicator
        # create value stays raw).
        self.assertLess(run.index("known = new List<GameNPC>(cache.NpcUpdateCache.Keys);"),
                        run.index("npc.GetQuestIndicator(player)"))
        self.assertIn("return (meaning, (byte)WireFor(player, npc, meaning));", run)
        # One NPC's exception keeps its marker and doesn't stop the others.
        self.assertIn("return (eQuestIndicator.None, LastSent.Last(player, npc));", run)


class EndingsTests(unittest.TestCase):
    def test_the_upstream_files_keep_their_endings_and_bom(self):
        for path, bom in ((GAME_NPC, False), (GAME_PLAYER, False), (CREATE, True), (EFFECT, False),
                          (ABSTRACT_QUEST, False), (DATA_QUEST, True), (DAILY, False), (WEEKLY, False),
                          (MONTHLY, False)):
            with open(path, "rb") as f:
                raw = f.read()
            self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"), path)
            self.assertEqual(raw.startswith(b"\xef\xbb\xbf"), bom, path)

    def test_the_fork_files_are_lf(self):
        for path in (QUEST_INDICATORS, SENT_STORE):
            with open(path, "rb") as f:
                raw = f.read()
            self.assertNotIn(b"\r", raw, path)
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), path)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to see them fail.**

Run: `python3 -B -m unittest deploy/tests/test_quest_indicators.py`
Expected: `FAILED (errors=3)` — the `GetQuestIndicator`, create-packet and quest-effect checks raise `ValueError:
substring not found`; the refresh and endings checks pass.

- [ ] **Step 3: `GetQuestIndicator` asks the rules.** It still returns the GM's `/indicator create` value first:

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/gameobjects/GameNPC.cs <<'EDIT'
<<<<<<< OLD
				return forced;

			// Available one ?
			if (CanShowOneQuest(player))
				return eQuestIndicator.Available;

			// Finishing one ?
			if (CanFinishOneQuest(player))
				return eQuestIndicator.Finish;

			return eQuestIndicator.None;
		}
=======
				return forced;

			// HearthDAoC: one set of rules for every NPC (QuestIndicators.For): turn in, then the current step, then a quest
			// to take whose minimum level is at most 15 below the player's. The quest lists are copied under their locks.
			AbstractQuest[] scripted;
			lock (_questListToGiveLock)
				scripted = m_questListToGive.Cast<AbstractQuest>().ToArray();
			DataQuest[] offered;
			lock (_dataQuestsLock)
				offered = DataQuestList.ToArray();
			return HearthDAoC.QuestIndicators.For(this, player, scripted, offered);
		}
>>>>>>> NEW
EDIT
```

- [ ] **Step 4: Both packet writers translate and record.** Line 208 of `PacketLib1124.cs` stays as it is (a source
check in `test_player_commands.py` pins it):

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/packets/Server/PacketLib1124.cs <<'EDIT'
<<<<<<< OLD
					eQuestIndicator questIndicator = npc.GetQuestIndicator(m_gameClient.Player);
=======
					eQuestIndicator questIndicator = npc.GetQuestIndicator(m_gameClient.Player);
					// HearthDAoC: the meaning becomes the value the client draws, recorded as sent to this player; a change also asks a refresh (QuestIndicators.cs; /indicator's values stay raw).
					questIndicator = HearthDAoC.QuestIndicators.SendingCreate(m_gameClient.Player, npc, questIndicator);
>>>>>>> NEW
EDIT
```
```bash
python3 /tmp/hdc-edit.py source/server/GameServer/packets/Server/PacketLib173.cs <<'EDIT'
<<<<<<< OLD
			if (m_gameClient.Player == null || npc == null)
				return;

			using (var pak = PooledObjectFactory.GetForTick<GSTCPPacketOut>().Init(GetPacketCode(eServerPackets.VisualEffect)))
=======
			if (m_gameClient.Player == null || npc == null)
				return;

			// HearthDAoC: the meaning becomes the value the client draws, recorded as sent to this player (QuestIndicators.cs; /indicator's values stay raw).
			indicator = HearthDAoC.QuestIndicators.Sending(m_gameClient.Player, npc, indicator);

			using (var pak = PooledObjectFactory.GetForTick<GSTCPPacketOut>().Init(GetPacketCode(eServerPackets.VisualEffect)))
>>>>>>> NEW
EDIT
```

- [ ] **Step 5: The old source check follows the new code.** `test_player_commands.py` cuts `GetQuestIndicator` at
`CanShowOneQuest(player)`, which is gone:

```bash
python3 /tmp/hdc-edit.py deploy/tests/test_player_commands.py <<'EDIT'
<<<<<<< OLD
        body = body[:body.index("CanShowOneQuest(player)")]
=======
        body = body[:body.index("HearthDAoC.QuestIndicators.For(")]
>>>>>>> NEW
EDIT
```

- [ ] **Step 6: Run the checks and the unit tests.**

Run: `python3 -B -m unittest deploy/tests/test_quest_indicators.py deploy/tests/test_player_commands.py`
Expected: `OK`.

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --filter "FullyQualifiedName~UT_QuestIndicators|FullyQualifiedName~UT_IndicatorSentStore|FullyQualifiedName~UT_QuestIndicatorProbe"`
Expected: the server builds with no error; `Passed!` with `Failed: 0` and `Passed: 85` (27 + 13 + the probe's 45).

Run: `git diff --numstat` — `GameNPC.cs` 9 added, 9 deleted; `PacketLib1124.cs` 2 added; `PacketLib173.cs` 3 added;
`test_player_commands.py` 1 added, 1 deleted; nothing else. (Thousands of changed lines mean the endings changed: undo
the file with `git checkout -- FILE` and use the helper.)

- [ ] **Step 7: Commit.**

```bash
git add deploy/tests/test_quest_indicators.py source/server/GameServer/gameobjects/GameNPC.cs source/server/GameServer/packets/Server/PacketLib1124.cs source/server/GameServer/packets/Server/PacketLib173.cs deploy/tests/test_player_commands.py
git commit -m "feat(indicators): NPCs and both packets use the scheme

GameNPC.GetQuestIndicator returns the rules' meaning (after the GM's
/indicator value); the create packet and the quest effect turn it into the
value the client draws (yellow, white or blue knot) and record it for the
refresh.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `/indicator` follows the scheme and names what the client draws

**Files:**
- Modify: `source/server/Tests/UnitTests/UT_QuestIndicatorProbe.cs` (expected texts; new tests)
- Modify: `source/server/GameServer/scripts/hearthdaoc/QuestIndicatorProbe.cs` (the rules it explains; what is drawn)
- Modify: `source/server/GameServer/scripts/hearthdaoc/IndicatorCommand.cs` (`effect` stays raw; reports name the wire
  value; scripted quests' minimum level)
- Modify: `deploy/tests/test_quest_indicators.py` (one more class)

**Interfaces:**
- Consumes: `QuestIndicators.FinishesHere`, `PendsHere`, `Shows`, `AvailableLevelSpan`, `Wire`, `WireFor`,
  `ScriptedMinLevel`, `SendRawEffect`, `QuestOffer` (Task 1).
- Produces: `GivenScriptedQuest` gains a last optional field `int? MinLevel = null`; `QuestIndicatorProbe.Drawn(eQuestIndicator
  wire)`, `Meaning(eQuestIndicator meaning)`, `Pends(DataQuest.eStepType)`, `Lights(GivenScriptedQuest, int)`,
  `Lights(GivenDataQuest, int)`; `RulesIndicator` gives Finish, then Pending, then Available; `FinishSteps` is gone.

- [ ] **Step 1: Write the failing tests.** Update `UT_QuestIndicatorProbe.cs` (LF fork file): the expected texts gain
what is drawn, the two tests of the old order become tests of the new one, and three tests are new:

```bash
python3 /tmp/hdc-edit.py source/server/Tests/UnitTests/UT_QuestIndicatorProbe.cs <<'EDIT'
<<<<<<< OLD
            "available: data quest 20478 Strange Beings (qualifies)",
            "  data quest 21500 Traveler's Way -- Supply Run: dependencies !#20478/21324 not met",
=======
            "available (a yellow knot): data quest 20478 Strange Beings (qualifies)",
            "  data quest 21500 Traveler's Way -- Supply Run: dependencies !#20478/21324 not met",
>>>>>>> NEW
<<<<<<< OLD
        Assert.That(QuestIndicatorProbe.Explain(facts)[0], Is.EqualTo("available: data quest 20478 Strange Beings (qualifies) and 1 more"));
=======
        Assert.That(QuestIndicatorProbe.Explain(facts)[0], Is.EqualTo("available (a yellow knot): data quest 20478 Strange Beings (qualifies) and 1 more"));
>>>>>>> NEW
<<<<<<< OLD
            "finish: data quest 20157 step 6 targets this NPC",
            "  data quest 20157 Entry Into Tomorrow: needs level 11",
            "  your data quest 20188 Rebellion Accepted is at step 2 (Kill) here, not a finishing step",
=======
            "finish (a blue knot): data quest 20157 step 6 targets this NPC",
            "  data quest 20157 Entry Into Tomorrow: needs level 11",
            "  your data quest 20188 Rebellion Accepted is at step 2 (Kill) here, a step that shows no marker",
>>>>>>> NEW
<<<<<<< OLD
        Assert.That(QuestIndicatorProbe.Explain(facts), Is.EqualTo(new[] { "finish: reward quest Wolf Pelts has every goal done" }));
=======
        Assert.That(QuestIndicatorProbe.Explain(facts), Is.EqualTo(new[] { "finish (a blue knot): reward quest Wolf Pelts has every goal done" }));
>>>>>>> NEW
<<<<<<< OLD
    [Test]
    public void AvailableComesBeforeFinish()
    {
        IndicatorFacts facts = Facts(eQuestIndicator.Available, new[] { Data(20478, "Strange Beings", qualifies: true) },
            steps: new[] { new StepAtNpc(20157, "Entry Into Tomorrow", 6, DataQuest.eStepType.InteractFinish) });
        Assert.That(QuestIndicatorProbe.RulesIndicator(facts), Is.EqualTo(eQuestIndicator.Available));
        Assert.That(QuestIndicatorProbe.Explain(facts)[^1],
            Is.EqualTo("  your data quest 20157 Entry Into Tomorrow is at step 6 (InteractFinish) here"));
    }
=======
    [Test]
    public void FinishComesBeforePendingAndAvailable()
    {
        IndicatorFacts facts = Facts(eQuestIndicator.Finish, new[] { Data(20478, "Strange Beings", qualifies: true) },
            steps: new[]
            {
                new StepAtNpc(20469, "Shades and Shadows", 2, DataQuest.eStepType.Interact),
                new StepAtNpc(20157, "Entry Into Tomorrow", 6, DataQuest.eStepType.InteractFinish),
            });
        Assert.That(QuestIndicatorProbe.RulesIndicator(facts), Is.EqualTo(eQuestIndicator.Finish));
        Assert.That(QuestIndicatorProbe.Explain(facts), Is.EqualTo(new[]
        {
            "finish (a blue knot): data quest 20157 step 6 targets this NPC",
            "  data quest 20478 Strange Beings: qualifies",
            "  your data quest 20469 Shades and Shadows is at step 2 (Interact) here",
        }));
    }

    [Test]
    public void PendingNamesTheStepAndComesBeforeAvailable()
    {
        IndicatorFacts facts = Facts(eQuestIndicator.Pending, new[] { Data(20478, "Strange Beings", qualifies: true) },
            steps: new[] { new StepAtNpc(20478, "Strange Beings", 1, DataQuest.eStepType.Interact) });
        Assert.That(QuestIndicatorProbe.RulesIndicator(facts), Is.EqualTo(eQuestIndicator.Pending));
        Assert.That(QuestIndicatorProbe.Explain(facts), Is.EqualTo(new[]
        {
            "pending (a white knot): data quest 20478 step 1 (Interact) is at this NPC",
            "  data quest 20478 Strange Beings: qualifies",
        }));
    }

    [Test]
    public void AQuestMoreThanFifteenLevelsBelowShowsNothing()
    {
        IndicatorFacts facts = Facts(eQuestIndicator.None, new[] { Data(20478, "Strange Beings", qualifies: true) },
            level: 30);
        Assert.That(QuestIndicatorProbe.RulesIndicator(facts), Is.EqualTo(eQuestIndicator.None));
        Assert.That(QuestIndicatorProbe.Explain(facts), Is.EqualTo(new[]
        {
            "none (nothing): 1 data quest, none qualifies (20478: qualifies, but its level 7 is more than 15 below yours)",
        }));
        Assert.That(QuestIndicatorProbe.RulesIndicator(facts with { Level = 22 }), Is.EqualTo(eQuestIndicator.Available));

        var epic = new GivenScriptedQuest("AncestralSecrets", true, 0, false, 1, MinLevel: 48);
        Assert.That(QuestIndicatorProbe.Lights(epic, 50), Is.True);
        Assert.That(QuestIndicatorProbe.Lights(epic with { MinLevel = 20 }, 50), Is.False);
        Assert.That(QuestIndicatorProbe.Lights(epic with { MinLevel = null }, 50), Is.True);
    }

    [Test]
    public void EachValueSaysWhatIsDrawn()
    {
        Assert.That(QuestIndicatorProbe.Drawn(eQuestIndicator.Available), Is.EqualTo("a yellow ring at the feet"));
        Assert.That(QuestIndicatorProbe.Drawn(eQuestIndicator.Lore), Is.EqualTo("a yellow knot"));
        Assert.That(QuestIndicatorProbe.Meaning(eQuestIndicator.Available), Is.EqualTo("available (a yellow knot)"));
        Assert.That(QuestIndicatorProbe.Meaning(eQuestIndicator.Pending), Is.EqualTo("pending (a white knot)"));
        Assert.That(QuestIndicatorProbe.Meaning(eQuestIndicator.Finish), Is.EqualTo("finish (a blue knot)"));
        Assert.That(QuestIndicatorProbe.Meaning(eQuestIndicator.Lore), Is.EqualTo("lore (nothing)"));
    }
>>>>>>> NEW
<<<<<<< OLD
            "none: 3 data quests, none qualifies (20478: needs level 7; 20157: needs level 11; 20001: already done)",
=======
            "none (nothing): 3 data quests, none qualifies (20478: needs level 7; 20157: needs level 11; 20001: already done)",
>>>>>>> NEW
<<<<<<< OLD
        Assert.That(QuestIndicatorProbe.Explain(Facts(eQuestIndicator.None)),
            Is.EqualTo(new[] { "none: this NPC gives no quests, and no quest of yours finishes here" }));
=======
        Assert.That(QuestIndicatorProbe.Explain(Facts(eQuestIndicator.None)),
            Is.EqualTo(new[] { "none (nothing): this NPC gives no quests, and no quest of yours finishes here" }));
>>>>>>> NEW
<<<<<<< OLD
            "none: 1 data quest and 1 scripted quest, none qualifies (Shadows_50: already done; 20478: you are doing it)"));
=======
            "none (nothing): 1 data quest and 1 scripted quest, none qualifies (Shadows_50: already done; 20478: you are doing it)"));
>>>>>>> NEW
<<<<<<< OLD
            "available: scripted quest Academy_50 (qualifies) and 1 more",
=======
            "available (a yellow knot): scripted quest Academy_50 (qualifies) and 1 more",
>>>>>>> NEW
<<<<<<< OLD
    [Test]
    public void OnlyFinishStepsFinish()
    {
        foreach (DataQuest.eStepType step in new[] { DataQuest.eStepType.KillFinish, DataQuest.eStepType.DeliverFinish,
                     DataQuest.eStepType.InteractFinish, DataQuest.eStepType.WhisperFinish, DataQuest.eStepType.CollectFinish })
            Assert.That(QuestIndicatorProbe.Finishes(step), Is.True, step.ToString());
        foreach (DataQuest.eStepType step in new[] { DataQuest.eStepType.Kill, DataQuest.eStepType.Deliver,
                     DataQuest.eStepType.Interact, DataQuest.eStepType.Whisper, DataQuest.eStepType.Collect,
                     DataQuest.eStepType.Search, DataQuest.eStepType.SearchFinish })
            Assert.That(QuestIndicatorProbe.Finishes(step), Is.False, step.ToString());
    }
=======
    [Test]
    public void OnlyTalkStepsFinishOrPend()
    {
        foreach (DataQuest.eStepType step in new[] { DataQuest.eStepType.DeliverFinish, DataQuest.eStepType.InteractFinish,
                     DataQuest.eStepType.WhisperFinish, DataQuest.eStepType.CollectFinish })
            Assert.That(QuestIndicatorProbe.Finishes(step), Is.True, step.ToString());
        foreach (DataQuest.eStepType step in new[] { DataQuest.eStepType.Deliver, DataQuest.eStepType.Interact,
                     DataQuest.eStepType.Whisper, DataQuest.eStepType.Collect })
            Assert.That(QuestIndicatorProbe.Pends(step), Is.True, step.ToString());
        foreach (DataQuest.eStepType step in new[] { DataQuest.eStepType.Kill, DataQuest.eStepType.KillFinish,
                     DataQuest.eStepType.Search, DataQuest.eStepType.SearchFinish })
        {
            Assert.That(QuestIndicatorProbe.Finishes(step), Is.False, step.ToString());
            Assert.That(QuestIndicatorProbe.Pends(step), Is.False, step.ToString());
        }
    }
>>>>>>> NEW
<<<<<<< OLD
            "available: BountyMaster decides; GameNPC's rules give none: this NPC gives no quests, and no quest of yours finishes here",
=======
            "available (a yellow knot): BountyMaster decides; GameNPC's rules give none: this NPC gives no quests, and no quest of yours finishes here",
>>>>>>> NEW
<<<<<<< OLD
            "available: data quest 20478 Strange Beings (qualifies)",
            "  SluaghbinderTrainer overrides GetQuestIndicator; here it agrees with GameNPC's rules",
=======
            "available (a yellow knot): data quest 20478 Strange Beings (qualifies)",
            "  SluaghbinderTrainer overrides GetQuestIndicator; here it agrees with GameNPC's rules",
>>>>>>> NEW
<<<<<<< OLD
            "You see lore (flags3 0x02), set by /indicator create for you only; the real one:",
            "none: this NPC gives no quests, and no quest of yours finishes here",
=======
            "You see lore (flags3 0x02: a yellow knot), set by /indicator create for you only; the real one:",
            "none (nothing): this NPC gives no quests, and no quest of yours finishes here",
>>>>>>> NEW
EDIT
```

Add the source check of `/indicator effect`:

```bash
python3 /tmp/hdc-edit.py deploy/tests/test_quest_indicators.py <<'EDIT'
<<<<<<< OLD
if __name__ == "__main__":
=======
class ProbeTests(unittest.TestCase):
    def test_indicator_effect_stays_raw(self):
        text = read(INDICATOR)
        self.assertIn("QuestIndicators.SendRawEffect(gm, npc, request.Effect);", text)
        self.assertNotIn("SendNPCsQuestEffect(npc, (eQuestIndicator)request.Effect)", text)


if __name__ == "__main__":
>>>>>>> NEW
EDIT
```

- [ ] **Step 2: Run them to see them fail.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --filter "FullyQualifiedName~UT_QuestIndicatorProbe"`
Expected: the build fails: `error CS0117` for `Pends`, `Lights`, `Drawn`, `Meaning` (not in `QuestIndicatorProbe`) and
for `MinLevel` in the `with { MinLevel = ... }` expressions, and `error CS1739` for the `MinLevel:` argument.

Run: `python3 -B -m unittest deploy/tests/test_quest_indicators.py`
Expected: `FAILED (failures=1)` (`test_indicator_effect_stays_raw`).

- [ ] **Step 3: The probe explains the scheme's rules.**

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/scripts/hearthdaoc/QuestIndicatorProbe.cs <<'EDIT'
<<<<<<< OLD
// A scripted quest the NPC gives. Qualifies is the quest's CheckQuestQualification; it shows only while the times
// finished and the one being done stay under MaxCount (GameNPC.CanShowOneQuest).
public sealed record GivenScriptedQuest(string Name, bool Qualifies, int Finished, bool Doing, int MaxCount);
=======
// A scripted quest the NPC gives. Qualifies is the quest's CheckQuestQualification; it shows only while the times
// finished and the one being done stay under MaxCount (GameNPC.CanShowOneQuest). MinLevel: its Level when its class
// declares one (QuestIndicators.ScriptedMinLevel), else null.
public sealed record GivenScriptedQuest(string Name, bool Qualifies, int Finished, bool Doing, int MaxCount,
    int? MinLevel = null);
>>>>>>> NEW
<<<<<<< OLD
    // The step types that finish a quest at their target (GameNPC.CanFinishOneQuest).
    private static readonly IReadOnlySet<DataQuest.eStepType> FinishSteps = new HashSet<DataQuest.eStepType>
    {
        DataQuest.eStepType.DeliverFinish, DataQuest.eStepType.InteractFinish, DataQuest.eStepType.KillFinish,
        DataQuest.eStepType.WhisperFinish, DataQuest.eStepType.CollectFinish,
    };

    public static string CreateNeeds => "create needs one of: " + string.Join(", ", Names);
=======
    public static string CreateNeeds => "create needs one of: " + string.Join(", ", Names);
>>>>>>> NEW
<<<<<<< OLD
    public static bool Finishes(DataQuest.eStepType stepType) => FinishSteps.Contains(stepType);

    public static bool Shows(GivenScriptedQuest quest) =>
        quest.Qualifies && quest.Finished + (quest.Doing ? 1 : 0) < quest.MaxCount;

    // GameNPC.GetQuestIndicator's rules: available if a quest can be given, else finish if one ends here, else none.
    public static eQuestIndicator RulesIndicator(IndicatorFacts facts)
    {
        if (facts.ScriptedQuests.Any(Shows) || facts.DataQuests.Any(q => q.ShowsIndicator && q.Qualifies))
            return eQuestIndicator.Available;
        if (facts.StepsHere.Any(s => Finishes(s.StepType)) || facts.RewardQuestsDone.Count > 0)
            return eQuestIndicator.Finish;
        return eQuestIndicator.None;
    }

    // Why a data quest does or doesn't light the NPC, in DataQuest.CheckQuestQualification's order.
    public static string Why(GivenDataQuest quest, int level)
    {
        string why = quest.Qualifies ? "qualifies" : WhyNot(quest, level);
=======
    // What the 1.127 client draws for a value on the wire (owner's /indicator test, 2026-10-10).
    public static string Drawn(eQuestIndicator wire) => wire switch
    {
        eQuestIndicator.None => "nothing",
        eQuestIndicator.Available => "a yellow ring at the feet",
        eQuestIndicator.Finish => "a blue knot",
        eQuestIndicator.Lesson => "a yellow book",
        eQuestIndicator.Lore => "a yellow knot",
        eQuestIndicator.Pending => "a white knot",
        _ => "nothing known",
    };

    // A meaning and what it draws (QuestIndicators.Wire): "available (a yellow knot)".
    public static string Meaning(eQuestIndicator meaning) => $"{Name(meaning)} ({Drawn(QuestIndicators.Wire(meaning))})";

    // The step types that turn in a quest at their target (blue), and the earlier ones that see it (white).
    public static bool Finishes(DataQuest.eStepType stepType) => QuestIndicators.FinishesHere(stepType);

    public static bool Pends(DataQuest.eStepType stepType) => QuestIndicators.PendsHere(stepType);

    public static bool Shows(GivenScriptedQuest quest) =>
        quest.Qualifies && quest.Finished + (quest.Doing ? 1 : 0) < quest.MaxCount;

    // A quest lights the NPC (yellow) when it shows and its minimum level is at most 15 below the player's.
    public static bool Lights(GivenScriptedQuest quest, int level) =>
        Shows(quest) && QuestIndicators.Shows(new QuestOffer(quest.MinLevel, true), level);

    public static bool Lights(GivenDataQuest quest, int level) =>
        quest.ShowsIndicator && QuestIndicators.Shows(new QuestOffer(quest.MinLevel, quest.Qualifies), level);

    private static bool TooLow(int? minLevel, int level) => minLevel is int min && level - min > QuestIndicators.AvailableLevelSpan;

    private static string TooLowText(int minLevel) =>
        $"qualifies, but its level {minLevel} is more than {QuestIndicators.AvailableLevelSpan} below yours";

    // GameNPC.GetQuestIndicator's rules (QuestIndicators.For): turn in, then the current step, then a quest to take.
    public static eQuestIndicator RulesIndicator(IndicatorFacts facts)
    {
        if (facts.StepsHere.Any(s => Finishes(s.StepType)) || facts.RewardQuestsDone.Count > 0)
            return eQuestIndicator.Finish;
        if (facts.StepsHere.Any(s => Pends(s.StepType)))
            return eQuestIndicator.Pending;
        if (facts.ScriptedQuests.Any(q => Lights(q, facts.Level)) || facts.DataQuests.Any(q => Lights(q, facts.Level)))
            return eQuestIndicator.Available;
        return eQuestIndicator.None;
    }

    // Why a data quest does or doesn't light the NPC, in DataQuest.CheckQuestQualification's order.
    public static string Why(GivenDataQuest quest, int level)
    {
        string why = !quest.Qualifies ? WhyNot(quest, level)
            : TooLow(quest.MinLevel, level) ? TooLowText(quest.MinLevel) : "qualifies";
>>>>>>> NEW
<<<<<<< OLD
    public static string Why(GivenScriptedQuest quest)
    {
        if (Shows(quest))
            return "qualifies";
=======
    public static string Why(GivenScriptedQuest quest, int level = 0)
    {
        if (Shows(quest))
            return TooLow(quest.MinLevel, level) ? TooLowText(quest.MinLevel.Value) : "qualifies";
>>>>>>> NEW
<<<<<<< OLD
        if (facts.Forced is eQuestIndicator forced)
            lines.Add($"You see {Name(forced)} ({CreateFlag(forced)}), set by /indicator create for you only; the real one:");

        eQuestIndicator rules = RulesIndicator(facts);
        object named = null;
        string reason;
        if (rules == eQuestIndicator.Available)
        {
            GivenScriptedQuest scripted = facts.ScriptedQuests.FirstOrDefault(Shows);
            GivenDataQuest data = facts.DataQuests.FirstOrDefault(q => q.ShowsIndicator && q.Qualifies);
            int count = facts.ScriptedQuests.Count(Shows) + facts.DataQuests.Count(q => q.ShowsIndicator && q.Qualifies);
=======
        if (facts.Forced is eQuestIndicator forced)
            lines.Add($"You see {Name(forced)} ({CreateFlag(forced)}: {Drawn(forced)}), set by /indicator create for you only; the real one:");

        eQuestIndicator rules = RulesIndicator(facts);
        object named = null;
        string reason;
        if (rules == eQuestIndicator.Available)
        {
            GivenScriptedQuest scripted = facts.ScriptedQuests.FirstOrDefault(q => Lights(q, facts.Level));
            GivenDataQuest data = facts.DataQuests.FirstOrDefault(q => Lights(q, facts.Level));
            int count = facts.ScriptedQuests.Count(q => Lights(q, facts.Level)) + facts.DataQuests.Count(q => Lights(q, facts.Level));
>>>>>>> NEW
<<<<<<< OLD
                : $"reward quest {facts.RewardQuestsDone[0]} has every goal done";
        }
        else
            reason = NoneReason(facts);

        if (facts.Actual == rules)
            lines.Add($"{Name(facts.Actual)}: {reason}");
        else
            lines.Add($"{Name(facts.Actual)}: {facts.OverridingClass ?? "the NPC"} decides; GameNPC's rules give {Name(rules)}: {reason}");

        if (rules != eQuestIndicator.None)
        {
            foreach (GivenScriptedQuest quest in facts.ScriptedQuests.Where(q => !ReferenceEquals(q, named)))
                lines.Add($"  scripted quest {quest.Name}: {Why(quest)}");
=======
                : $"reward quest {facts.RewardQuestsDone[0]} has every goal done";
        }
        else if (rules == eQuestIndicator.Pending)
        {
            StepAtNpc step = facts.StepsHere.First(s => Pends(s.StepType));
            named = step;
            reason = $"data quest {step.QuestId} step {step.Step} ({step.StepType}) is at this NPC";
        }
        else
            reason = NoneReason(facts);

        if (facts.Actual == rules)
            lines.Add($"{Meaning(facts.Actual)}: {reason}");
        else
            lines.Add($"{Meaning(facts.Actual)}: {facts.OverridingClass ?? "the NPC"} decides; GameNPC's rules give {Name(rules)}: {reason}");

        if (rules != eQuestIndicator.None)
        {
            foreach (GivenScriptedQuest quest in facts.ScriptedQuests.Where(q => !ReferenceEquals(q, named)))
                lines.Add($"  scripted quest {quest.Name}: {Why(quest, facts.Level)}");
>>>>>>> NEW
<<<<<<< OLD
            lines.Add($"  your data quest {step.QuestId} {step.QuestName} is at step {step.Step} ({step.StepType}) here" +
                (Finishes(step.StepType) ? string.Empty : ", not a finishing step"));
=======
            lines.Add($"  your data quest {step.QuestId} {step.QuestName} is at step {step.Step} ({step.StepType}) here" +
                (Finishes(step.StepType) || Pends(step.StepType) ? string.Empty : ", a step that shows no marker"));
>>>>>>> NEW
<<<<<<< OLD
        IEnumerable<string> why = facts.ScriptedQuests.Select(q => $"{q.Name}: {Why(q)}")
=======
        IEnumerable<string> why = facts.ScriptedQuests.Select(q => $"{q.Name}: {Why(q, facts.Level)}")
>>>>>>> NEW
EDIT
```

- [ ] **Step 4: The command: `effect` stays raw, the reports name the wire value, scripted quests carry their level.**

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/scripts/hearthdaoc/IndicatorCommand.cs <<'EDIT'
<<<<<<< OLD
                gm.Out.SendNPCsQuestEffect(npc, (eQuestIndicator)request.Effect);
=======
                QuestIndicators.SendRawEffect(gm, npc, request.Effect);
>>>>>>> NEW
<<<<<<< OLD
    // What the create packet just sent said: GetQuestIndicator is what PacketLib1124.SendNPCCreate asked.
    private static string Created(GameNPC npc, GamePlayer gm, out eQuestIndicator sent)
    {
        sent = npc.GetQuestIndicator(gm);
        return $"{npc.Name} is back on your client; its create packet said {QuestIndicatorProbe.Name(sent)} " +
            $"({QuestIndicatorProbe.CreateFlag(sent)}).";
    }
=======
    // What the create packet just sent said: GetQuestIndicator is what PacketLib1124.SendNPCCreate asked, and
    // QuestIndicators.WireFor what it put in the flags (the table, or an /indicator create value as it is).
    private static string Created(GameNPC npc, GamePlayer gm, out eQuestIndicator sent)
    {
        sent = npc.GetQuestIndicator(gm);
        eQuestIndicator wire = QuestIndicators.WireFor(gm, npc, sent);
        return $"{npc.Name} is back on your client; its create packet said {QuestIndicatorProbe.Name(wire)} " +
            $"({QuestIndicatorProbe.CreateFlag(wire)}: {QuestIndicatorProbe.Drawn(wire)}).";
    }
>>>>>>> NEW
<<<<<<< OLD
            Say(client, $"{text} Then the quest effect: byte {(byte)real}.");
=======
            Say(client, $"{text} Then the quest effect: byte {(byte)QuestIndicators.WireFor(gm, npc, real)}.");
>>>>>>> NEW
<<<<<<< OLD
            scripted.Add(new GivenScriptedQuest(quest.Name, quest.CheckQuestQualification(player),
                player.HasFinishedQuest(type), player.IsDoingQuest(type) != null, quest.MaxQuestCount));
=======
            scripted.Add(new GivenScriptedQuest(quest.Name, quest.CheckQuestQualification(player),
                player.HasFinishedQuest(type), player.IsDoingQuest(type) != null, quest.MaxQuestCount,
                QuestIndicators.ScriptedMinLevel(quest)));
>>>>>>> NEW
EDIT
```

- [ ] **Step 5: Run the tests.**

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --filter "FullyQualifiedName~UT_QuestIndicatorProbe|FullyQualifiedName~UT_QuestIndicators|FullyQualifiedName~UT_IndicatorSentStore"`
Expected: `Passed!` with `Failed: 0` and `Passed: 88` (the probe's 48 + 27 + 13).

Run: `python3 -B -m unittest deploy/tests/test_quest_indicators.py deploy/tests/test_player_commands.py`
Expected: `OK`.

- [ ] **Step 6: Commit.**

```bash
git add source/server/Tests/UnitTests/UT_QuestIndicatorProbe.cs source/server/GameServer/scripts/hearthdaoc/QuestIndicatorProbe.cs source/server/GameServer/scripts/hearthdaoc/IndicatorCommand.cs deploy/tests/test_quest_indicators.py
git commit -m "feat(indicator): /indicator follows the scheme and names what the client draws

The bare command explains the scheme's rules (turn in, then the current
step, then a quest to take within 15 levels) and names the knot each value
draws; effect and create stay raw, past the scheme's table.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Level, class, quest and rollover changes refresh the markers

**Files:**
- Modify: `deploy/tests/test_quest_indicators.py` (the hook checks)
- Modify: `source/server/GameServer/gameobjects/GamePlayer.cs` (the `Level` setter, `SetCharacterClass`, `AddQuest`)
- Modify: `source/server/GameServer/quests/QuestsMgr/AbstractQuest.cs` (the `Step` setter)
- Modify: `source/server/GameServer/quests/QuestsMgr/DataQuest.cs` (the `Step` setter, `FinishQuest`, `AbortQuest`, the
  InteractComplete and KillComplete finishes)
- Modify: `source/server/GameServer/ECS-Services/DailyQuestService.cs`, `WeeklyQuestService.cs`, `MonthlyQuestService.cs`
- Modify: `source/server/GameServer/scripts/hearthdaoc/EpicCommand.cs` (`done`, `reset`)

**Interfaces:**
- Consumes: `QuestIndicators.Refresh(GamePlayer)` (Task 2; null-safe, only queues, safe under any lock and from any
  thread). From upstream files it is written `HearthDAoC.QuestIndicators.Refresh(...)` (they are in `DOL.GS` or
  `DOL.GS.Quests`); `EpicCommand.cs` already uses `DOL.GS.HearthDAoC`.
- Produces: nothing new; every change of level, class or quests, and every rollover, asks one refresh.

Notes: `AbstractQuest.FinishQuest` and `AbortQuest` need no line: both start with `Step = -2;`/`Step = -1;`, which goes
through the setter (a check pins that). `RewardQuest.FinishQuest` calls the base. `DataQuest`'s `Step`, `FinishQuest` and
`AbortQuest` don't, so each gets its own line. Leave the `if (QuestList.Count > 25)` lines of `AddQuest` alone (issue
#112). Login fills the quest lists directly; no refresh is needed there (the client gets every NPC with its create packet).

- [ ] **Step 1: Write the failing hook checks.**

```bash
python3 /tmp/hdc-edit.py deploy/tests/test_quest_indicators.py <<'EDIT'
<<<<<<< OLD
if __name__ == "__main__":
=======
class RefreshHookTests(unittest.TestCase):
    """Who asks for a refresh (spec 3.3)."""

    def test_the_level_setter(self):
        body = between(read(GAME_PLAYER), "public override byte Level", "\n        }\n")
        marked(self, body, "HearthDAoC.QuestIndicators.Refresh(this);")
        # After the level-up handling, on every change (up or down).
        self.assertLess(body.index("Out.SendLevelUpSound();"), body.index("QuestIndicators.Refresh(this);"))

    def test_the_class_change(self):
        body = between(read(GAME_PLAYER), "public virtual bool SetCharacterClass(int id)", "\n        }\n")
        marked(self, body, "HearthDAoC.QuestIndicators.Refresh(this);")
        self.assertLess(body.index("m_characterClass = cl;"), body.index("QuestIndicators.Refresh(this);"))

    def test_add_quest(self):
        body = between(read(GAME_PLAYER), "public bool AddQuest(AbstractQuest quest)", "\n        }\n")
        marked(self, body, "HearthDAoC.QuestIndicators.Refresh(this);")
        self.assertLess(body.index("QuestList.TryAdd(quest, index);"), body.index("QuestIndicators.Refresh(this);"))

    def test_the_step_setter_and_what_relies_on_it(self):
        text = read(ABSTRACT_QUEST)
        step = between(text, "public virtual int Step", "\n        }\n")
        marked(self, step, "HearthDAoC.QuestIndicators.Refresh(m_questPlayer);")
        # FinishQuest and AbortQuest go through the setter first, so they need no line of their own.
        finish = between(text, "public virtual void FinishQuest()", "\n        }\n")
        abort = between(text, "public virtual void AbortQuest()", "\n        }\n")
        self.assertRegex(finish, r"\{\s*Step = -2;")
        self.assertRegex(abort, r"\{\s*Step = -1;")

    def test_the_data_quest_overrides_that_skip_the_base(self):
        text = read(DATA_QUEST)
        step = between(text, "public override int Step", "\n\t\t}\n")
        marked(self, step, "HearthDAoC.QuestIndicators.Refresh(m_questPlayer);")
        finish = between(text, "public virtual bool FinishQuest(GameObject obj, bool checkCustomStep)", "\n\t\t}\n")
        marked(self, finish, "HearthDAoC.QuestIndicators.Refresh(m_questPlayer);")
        self.assertLess(finish.index("QuestIndicators.Refresh"), finish.rindex("return true;"))
        abort = between(text, "public override void AbortQuest()", "\n\t\t}\n")
        marked(self, abort, "HearthDAoC.QuestIndicators.Refresh(m_questPlayer);")

    def test_quests_finished_on_the_spot(self):
        # InteractComplete (CheckOfferQuest) and KillComplete (OnLivingIsDying) fill the finished list directly.
        text = read(DATA_QUEST)
        self.assertEqual(len(re.findall(
            r"player\.Out\.SendQuestListUpdate\(\);\n\t+HearthDAoC\.QuestIndicators\.Refresh\(player\); // HearthDAoC:",
            text)), 2)

    def test_the_daily_weekly_and_monthly_rollovers(self):
        # The rollover makes those quests available again: their givers' knots come back (owner keeps them, 2026-10-11).
        for path, kind in ((DAILY, "DailyQuest"), (WEEKLY, "WeeklyQuest"), (MONTHLY, "MonthlyQuest")):
            text = read(path)
            call = "HearthDAoC.QuestIndicators.Refresh(client.Player);"
            marked(self, text, call)
            self.assertLess(text.index(f"client.Player?.RemoveFinishedQuests(x => x is Quests.{kind});"),
                            text.index(call), path)

    def test_epic_done_and_reset(self):
        text = read(EPIC)
        for name in ("private void Done(", "private void Reset("):
            body = between(text, name, "\n    }\n")
            self.assertLess(body.index("target.Out.SendQuestListUpdate();"),
                            body.index("QuestIndicators.Refresh(target);"), name)

    def test_upstream_files_that_call_the_fork(self):
        # Every hook in upstream files, for upstream syncs (FORK.md).
        calls = {}
        for folder, _, names in os.walk(GAME_SERVER):
            if folder.startswith(FORK):
                continue
            for name in names:
                if name.endswith(".cs"):
                    count = len(re.findall(r"HearthDAoC\.QuestIndicators\.", read(os.path.join(folder, name))))
                    if count:
                        calls[name] = count
        self.assertEqual(calls, {
            "GameNPC.cs": 1,
            "PacketLib1124.cs": 1,
            "PacketLib173.cs": 1,
            "GamePlayer.cs": 3,
            "AbstractQuest.cs": 1,
            "DataQuest.cs": 5,
            "DailyQuestService.cs": 1,
            "WeeklyQuestService.cs": 1,
            "MonthlyQuestService.cs": 1,
        })


if __name__ == "__main__":
>>>>>>> NEW
EDIT
```

- [ ] **Step 2: Run them to see them fail.**

Run: `python3 -B -m unittest deploy/tests/test_quest_indicators.py`
Expected: `FAILED (failures=8, errors=1)`: the 9 `RefreshHookTests` find no `QuestIndicators.Refresh` where they look
(`test_epic_done_and_reset` as a `ValueError`); the other 7 tests pass.

- [ ] **Step 3: `GamePlayer`** (spaces, CRLF, no BOM):

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/gameobjects/GamePlayer.cs <<'EDIT'
<<<<<<< OLD
                        //update the mob colours
                        Out.SendLevelUpSound();
                    }
                }
            }
=======
                        //update the mob colours
                        Out.SendLevelUpSound();
                    }
                }

                HearthDAoC.QuestIndicators.Refresh(this); // HearthDAoC: quest markers follow the level at once, up or down (quest indicators spec, 3.3).
            }
>>>>>>> NEW
<<<<<<< OLD
                Group.UpdateMember(this, false, true);
            }
            return true;
=======
                Group.UpdateMember(this, false, true);
            }
            HearthDAoC.QuestIndicators.Refresh(this); // HearthDAoC: quest markers follow a class change at once (trainer, /player class).
            return true;
>>>>>>> NEW
<<<<<<< OLD
            quest.OnQuestAssigned(this);
            Out.SendQuestUpdate(quest);
            return true;
=======
            quest.OnQuestAssigned(this);
            Out.SendQuestUpdate(quest);
            HearthDAoC.QuestIndicators.Refresh(this); // HearthDAoC: quest markers change when a quest is taken (quest indicators spec, 3.3).
            return true;
>>>>>>> NEW
EDIT
```

- [ ] **Step 4: `AbstractQuest`** (spaces, CRLF, no BOM):

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/quests/QuestsMgr/AbstractQuest.cs <<'EDIT'
<<<<<<< OLD
                m_questPlayer.Out.SendQuestUpdate(this);
            }
=======
                m_questPlayer.Out.SendQuestUpdate(this);
                HearthDAoC.QuestIndicators.Refresh(m_questPlayer); // HearthDAoC: quest markers change when a quest moves, finishes or is abandoned.
            }
>>>>>>> NEW
EDIT
```

- [ ] **Step 5: `DataQuest`** (tabs, CRLF, BOM): the `Step` setter, `FinishQuest`, `AbortQuest`, then the two
on-the-spot finishes (InteractComplete in `CheckOfferQuest`, 7 tabs; KillComplete in `OnLivingIsDying`, 8 tabs):

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/quests/QuestsMgr/DataQuest.cs <<'EDIT'
<<<<<<< OLD
					if (m_charQuest.Step != oldStep)
					{
						GameServer.Database.SaveObject(m_charQuest);
					}
=======
					if (m_charQuest.Step != oldStep)
					{
						GameServer.Database.SaveObject(m_charQuest);
						HearthDAoC.QuestIndicators.Refresh(m_questPlayer); // HearthDAoC: quest markers change when a data quest moves to its next step.
					}
>>>>>>> NEW
<<<<<<< OLD
			foreach (GameNPC npc in m_questPlayer.GetNPCsInRadius(WorldMgr.VISIBILITY_DISTANCE))
			{
				UpdateQuestIndicator(npc, m_questPlayer);
			}

			return true;
=======
			foreach (GameNPC npc in m_questPlayer.GetNPCsInRadius(WorldMgr.VISIBILITY_DISTANCE))
			{
				UpdateQuestIndicator(npc, m_questPlayer);
			}

			HearthDAoC.QuestIndicators.Refresh(m_questPlayer); // HearthDAoC: quest markers change when a data quest is finished.
			return true;
>>>>>>> NEW
<<<<<<< OLD
			if (m_startNPC != null)
				UpdateQuestIndicator(m_startNPC, m_questPlayer);
		}
=======
			if (m_startNPC != null)
				UpdateQuestIndicator(m_startNPC, m_questPlayer);
			HearthDAoC.QuestIndicators.Refresh(m_questPlayer); // HearthDAoC: quest markers change when a data quest is abandoned.
		}
>>>>>>> NEW
<<<<<<< OLD
								player.AddFinishedQuest(this);

							player.Out.SendQuestListUpdate();
=======
								player.AddFinishedQuest(this);

							player.Out.SendQuestListUpdate();
							HearthDAoC.QuestIndicators.Refresh(player); // HearthDAoC: a quest finished on the spot can unlock another NPC's quest.
>>>>>>> NEW
<<<<<<< OLD
									player.AddFinishedQuest(this);

								player.Out.SendQuestListUpdate();
=======
									player.AddFinishedQuest(this);

								player.Out.SendQuestListUpdate();
								HearthDAoC.QuestIndicators.Refresh(player); // HearthDAoC: a quest finished on the spot can unlock another NPC's quest.
>>>>>>> NEW
EDIT
```

- [ ] **Step 6: The rollovers** (spaces, CRLF, no BOM; `RemoveFinishedQuests` makes those quests available again):

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/ECS-Services/DailyQuestService.cs <<'EDIT'
<<<<<<< OLD
                    client.Player?.RemoveFinishedQuests(x => x is Quests.DailyQuest);
=======
                    client.Player?.RemoveFinishedQuests(x => x is Quests.DailyQuest);
                    HearthDAoC.QuestIndicators.Refresh(client.Player); // HearthDAoC: the givers of daily quests show their knot again at the rollover.
>>>>>>> NEW
EDIT
```
```bash
python3 /tmp/hdc-edit.py source/server/GameServer/ECS-Services/WeeklyQuestService.cs <<'EDIT'
<<<<<<< OLD
                    client.Player?.RemoveFinishedQuests(x => x is Quests.WeeklyQuest);
=======
                    client.Player?.RemoveFinishedQuests(x => x is Quests.WeeklyQuest);
                    HearthDAoC.QuestIndicators.Refresh(client.Player); // HearthDAoC: the givers of weekly quests show their knot again at the rollover.
>>>>>>> NEW
EDIT
```
```bash
python3 /tmp/hdc-edit.py source/server/GameServer/ECS-Services/MonthlyQuestService.cs <<'EDIT'
<<<<<<< OLD
                    client.Player?.RemoveFinishedQuests(x => x is Quests.MonthlyQuest);
=======
                    client.Player?.RemoveFinishedQuests(x => x is Quests.MonthlyQuest);
                    HearthDAoC.QuestIndicators.Refresh(client.Player); // HearthDAoC: the givers of monthly quests show their knot again at the rollover.
>>>>>>> NEW
EDIT
```

- [ ] **Step 7: `/epic done` and `reset`** (fork file, LF; they change the quest lists directly):

```bash
python3 /tmp/hdc-edit.py source/server/GameServer/scripts/hearthdaoc/EpicCommand.cs <<'EDIT'
<<<<<<< OLD
        target.Out.SendQuestListUpdate();
        DisplayMessage(client, ids.Count == 0
=======
        target.Out.SendQuestListUpdate();
        QuestIndicators.Refresh(target); // the markers around the character follow the new quest lists at once
        DisplayMessage(client, ids.Count == 0
>>>>>>> NEW
<<<<<<< OLD
        target.Out.SendQuestListUpdate();
        DisplayMessage(client, $"{target.Name}: the chain is reset." +
=======
        target.Out.SendQuestListUpdate();
        QuestIndicators.Refresh(target); // the markers around the character follow the new quest lists at once
        DisplayMessage(client, $"{target.Name}: the chain is reset." +
>>>>>>> NEW
EDIT
```

- [ ] **Step 8: Run everything.**

Run: `python3 -B -m unittest deploy/tests/test_quest_indicators.py`
Expected: `Ran 16 tests` ... `OK`.

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --filter "FullyQualifiedName~UT_"`
Expected: the server builds with no error; `Passed!` with `Failed: 0` and `Passed: 3093`.

Run: `git diff --numstat` — added lines only: `GamePlayer.cs` 4 (the level hook brings a blank line), `AbstractQuest.cs` 1,
`DataQuest.cs` 5, each `*QuestService.cs` 1, `EpicCommand.cs` 2, `test_quest_indicators.py` 86; nothing else.

- [ ] **Step 9: Commit.**

```bash
git add deploy/tests/test_quest_indicators.py source/server/GameServer/gameobjects/GamePlayer.cs source/server/GameServer/quests/QuestsMgr/AbstractQuest.cs source/server/GameServer/quests/QuestsMgr/DataQuest.cs source/server/GameServer/ECS-Services/DailyQuestService.cs source/server/GameServer/ECS-Services/WeeklyQuestService.cs source/server/GameServer/ECS-Services/MonthlyQuestService.cs source/server/GameServer/scripts/hearthdaoc/EpicCommand.cs
git commit -m "feat(indicators): level, class, quest and rollover changes refresh the markers

One marked QuestIndicators.Refresh line where a player's level, class or
quests change (the Level setter, SetCharacterClass, AddQuest, the Step
setters, DataQuest's FinishQuest and AbortQuest, the on-the-spot finishes,
/epic done and reset) and at the daily, weekly and monthly rollovers.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The record and the owner's in-game checks

**Files:**
- Modify: `docs/fork/FORK.md` (the `/epic` and `/indicator` rows; a new row after `/indicator`)
- Modify: `docs/fork/verification/sub4-test-guide.md` (a `###` subsection at the end of the existing section "4. Quest
  indicators (`/indicator`)", just before its "Results go in ..." line)

**Interfaces:** none (documentation).

- [ ] **Step 1: FORK.md.** The server-code table (4 columns: Change | Files | Why | Upstream):

```bash
python3 /tmp/hdc-edit.py docs/fork/FORK.md <<'EDIT'
<<<<<<< OLD
| `/epic` (GM only) | `GameServer/scripts/hearthdaoc/EpicChain.cs` (the decisions), `GameServer/scripts/hearthdaoc/EpicCommand.cs` (the command), test `Tests/UnitTests/UT_EpicChain.cs` | Testing an epic chain quickly: list, `done <level>`, `goto`, `reset`. `goto` leads to the active stage's marker, or to the next step's giver: of the steps whose dependencies are met, the one given in the character's region (the Shrouded Isles 7 for a character in the Isles), else the first. A step that needs only quests closed to the character is closed too (after the Shrouded Isles 7, Camelot's 11), and the list says why | Fork-only |
=======
| `/epic` (GM only) | `GameServer/scripts/hearthdaoc/EpicChain.cs` (the decisions), `GameServer/scripts/hearthdaoc/EpicCommand.cs` (the command), test `Tests/UnitTests/UT_EpicChain.cs` | Testing an epic chain quickly: list, `done <level>`, `goto`, `reset`. `goto` leads to the active stage's marker, or to the next step's giver: of the steps whose dependencies are met, the one given in the character's region (the Shrouded Isles 7 for a character in the Isles), else the first. A step that needs only quests closed to the character is closed too (after the Shrouded Isles 7, Camelot's 11), and the list says why. `done` and `reset` refresh the quest markers around the character (quest indicators, row below) | Fork-only |
>>>>>>> NEW
<<<<<<< OLD
| `/indicator` (GM only, a test tool) | `GameServer/scripts/hearthdaoc/QuestIndicatorProbe.cs` (the decisions and the store), `GameServer/scripts/hearthdaoc/IndicatorCommand.cs` (the command and the store's game wiring), `GameServer/gameobjects/GameNPC.cs` (`GetQuestIndicator` asks the GM's value first: one block, marked), test `Tests/UnitTests/UT_QuestIndicatorProbe.cs`, source checks `deploy/tests/test_player_commands.py` | The owner's client (1.127) shows two indicator styles, a ring at an NPC's feet and a knot over its head, and the server reaches it two ways: the flags of the NPC create packet (`PacketLib1124.SendNPCCreate`) and the quest effect packet (`PacketLib173.SendNPCsQuestEffect`). To choose a scheme, the owner needs to see each way and value once (2026-10-10). On the GM's target, for the GM's client only: `effect <0-255>` sends the quest effect with a raw byte; `create <none|available|finish|lesson|lore|pending>` makes the create packet carry that indicator and re-creates the NPC; `refresh` re-sends the real indicator both ways, the create packet first; `clear` drops the GM's values; the bare command says what the real indicator is and why (each data and scripted quest, the steps at the NPC, and a class that overrides `GetQuestIndicator`). A value lasts until `clear` or `refresh`, the GM's logout, or the NPC leaving the world (death included). A class that overrides `GetQuestIndicator` without asking GameNPC's first never sees the value; the command says so. The owner's first run (2026-10-10): the quest effect drew nothing (`/mob refreshquests` on Elaru, a level-7 Infiltrator beside her), a new login drew her indicator. So the re-create copies a login's view of the NPC: the remove packet, then, 1 second later (the client has dropped the NPC by then, and the GM sees it go and come back), `ClientService.CreateObjectForPlayer`, the create an NPC gets when it comes into view or when the client asks for an object it lacks: the create packet, the equipment, the GM's target again | No: a test tool |
=======
| `/indicator` (GM only, a test tool) | `GameServer/scripts/hearthdaoc/QuestIndicatorProbe.cs` (the decisions and the store), `GameServer/scripts/hearthdaoc/IndicatorCommand.cs` (the command and the store's game wiring), `GameServer/gameobjects/GameNPC.cs` (`GetQuestIndicator` asks the GM's value first: one block, marked), test `Tests/UnitTests/UT_QuestIndicatorProbe.cs`, source checks `deploy/tests/test_player_commands.py` | The owner's client (1.127) shows two indicator styles, a ring at an NPC's feet and a knot over its head, and the server reaches it two ways: the flags of the NPC create packet (`PacketLib1124.SendNPCCreate`) and the quest effect packet (`PacketLib173.SendNPCsQuestEffect`). To choose a scheme, the owner needs to see each way and value once (2026-10-10). On the GM's target, for the GM's client only: `effect <0-255>` sends the quest effect with a raw byte; `create <none|available|finish|lesson|lore|pending>` makes the create packet carry that indicator and re-creates the NPC; `refresh` re-sends the real indicator both ways, the create packet first; `clear` drops the GM's values; the bare command says what the real indicator is and why (each data and scripted quest, the steps at the NPC, and a class that overrides `GetQuestIndicator`). A value lasts until `clear` or `refresh`, the GM's logout, or the NPC leaving the world (death included). A class that overrides `GetQuestIndicator` without asking GameNPC's first never sees the value; the command says so. The owner's first run (2026-10-10): the quest effect drew nothing (`/mob refreshquests` on Elaru, a level-7 Infiltrator beside her), a new login drew her indicator. So the re-create copies a login's view of the NPC: the remove packet, then, 1 second later (the client has dropped the NPC by then, and the GM sees it go and come back), `ClientService.CreateObjectForPlayer`, the create an NPC gets when it comes into view or when the client asks for an object it lacks: the create packet, the equipment, the GM's target again. Since the quest indicators (row below), `effect` and `create` stay raw (past the scheme's table), and the bare command follows the scheme's rules and names what the client draws | No: a test tool |
| Quest indicators: one scheme (yellow, white and blue knots) that stays current | `GameServer/scripts/hearthdaoc/QuestIndicators.cs` (new: the rules, the meaning-to-wire table, the refresh), `GameServer/scripts/hearthdaoc/IndicatorSentStore.cs` (new: the value last sent per player and NPC, the queued refresh), `GameServer/gameobjects/GameNPC.cs` (`GetQuestIndicator` asks `QuestIndicators.For` after the `/indicator` block, marked), `GameServer/packets/Server/PacketLib1124.cs` (`SendNPCCreate`) and `GameServer/packets/Server/PacketLib173.cs` (`SendNPCsQuestEffect`): the meaning becomes the value the client draws and is recorded, and a create that changes the value also asks a refresh (one marked line each); one marked `QuestIndicators.Refresh` line each in `GameServer/gameobjects/GamePlayer.cs` (the `Level` setter, `SetCharacterClass`, `AddQuest`), `GameServer/quests/QuestsMgr/AbstractQuest.cs` (the `Step` setter, which `FinishQuest` and `AbortQuest` go through), `GameServer/quests/QuestsMgr/DataQuest.cs` (the `Step` setter, `FinishQuest`, `AbortQuest`, the InteractComplete and KillComplete finishes) and `GameServer/ECS-Services/DailyQuestService.cs`, `WeeklyQuestService.cs`, `MonthlyQuestService.cs` (the rollovers); `GameServer/scripts/hearthdaoc/EpicCommand.cs` (`done`, `reset`), `GameServer/scripts/hearthdaoc/IndicatorCommand.cs` and `QuestIndicatorProbe.cs`; tests `Tests/UnitTests/UT_QuestIndicators.cs`, `Tests/UnitTests/UT_IndicatorSentStore.cs`, source checks `deploy/tests/test_quest_indicators.py` | One marker per NPC from one set of rules ([spec](specs/2026-10-11-quest-indicators-design.md)): a yellow knot for a quest to take (not more than 15 levels below the player's level, the 1.73 rule; none for daily, weekly and monthly quests, which follow the player's level), a white knot for the current step, a blue knot to turn in, nothing for kill targets (KillFinish no longer turns in at a monster), Atlas master trainers and the buff merchant ("lore" now draws nothing); the 1.73 indicators and the later knots are playability additions to the 1.65 era (owner, 2026-10-11). The server's "available" drew the 1.73 ring and "finish" the blue knot (owner's `/indicator` test 2026-10-10), and a marker was only worked out when an NPC came into view; now a level, class or quest change, or a daily, weekly or monthly rollover, re-sends every changed marker around the player within one game-loop tick, by the quest effect alone (it draws and clears on any NPC: owner's check 2026-10-11) | Candidate, after the in-game run (ask the owner first): the refresh on level and quest changes, and the KillFinish fix; the scheme is fork-only |
>>>>>>> NEW
EDIT
```

- [ ] **Step 2: The test guide.**

```bash
python3 /tmp/hdc-edit.py docs/fork/verification/sub4-test-guide.md <<'EDIT'
<<<<<<< OLD
Results go in `docs/fork/verification/sub4-ingame.md`.
=======
### Markers that stay current (quest indicators)

The scheme: a yellow knot over an NPC offers a quest you can take, a white knot is the NPC your current step sends you
to, a blue knot is where you turn a quest in; nothing else (no ring at the feet). Each of these should change at once,
without a new login:

1. A new Infiltrator in Caer Gothwaite, `/player level 7`: Elaru shows a yellow knot.
2. Accept "Strange Beings": Elaru's knot goes and Tage shows a white knot; each next step's NPC turns white as the
   quest moves (Kimmy Glaze); on the last step Adam Glaze shows a blue knot; after turning in, Elaru shows no knot
   until level 11, then a yellow one for "Shades and Shadows".
3. A level-30 character near Elaru: no knot (more than 15 levels above the quest's level 7).
4. An Atlas master trainer: no knot.
5. "Cleric Mulgrut" (Hugh Gallen at Prydwen Keep, level 5), on its last step: no blue knot on Mulgrut Maggot.
6. `/epic reset`, then `/epic done 15`: the markers around you change at once.
7. A level-50 character at Castle Sauvage (Albion's frontier gate in Forest Sauvage): Hector shows a yellow knot while
   "[Group Daily] A Team Building Exercise" is open to you (daily quests have no level rule).
8. `/indicator` on any NPC names its meaning and what the client draws, e.g. "available (a yellow knot): ...".
9. A level-7 character by Elaru (yellow knot): walk about 4,000 units away, `/player level 23`, walk back: no knot on
   her (the server's create for an NPC your client still drew is followed by a quest effect).

Results go in `docs/fork/verification/sub4-ingame.md`.
>>>>>>> NEW
EDIT
```

- [ ] **Step 3: Full verification** (the code is committed; only the two docs files are not yet; one suite after the other).

Run: `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=0 dotnet test source/server/Tests/Tests.csproj --filter "FullyQualifiedName~UT_"`
Expected: `Passed!` with `Failed: 0` and `Passed: 3093` (see the note on the upstream flaky test).

Run: `HDC_TEST_WORLD=/home/farral/Games/OfflineDAoC-archive/test-world/clean-classic-0.35.db python3 -B -m unittest discover -s deploy/tests -t deploy`
Expected: `Ran 414 tests` ... `OK (skipped=11)`.

Run: `git status --short` — clean apart from the two docs files; `serverconfig.xml` is ignored.

- [ ] **Step 4: Commit.**

```bash
git add docs/fork/FORK.md docs/fork/verification/sub4-test-guide.md
git commit -m "docs(indicators): FORK.md rows and the owner's in-game checks

FORK.md records the scheme, every upstream file it touches and the refresh;
the /epic and /indicator rows say what changed for them. Section 4 of the
sub-project 4 test guide lists the in-game checks.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

After Task 6 the controller pushes the branch, opens the PR with a "To update" section (owner: `./hdc update`, no
world data change, then the in-game checks of the test guide; players: nothing) and watches CI.

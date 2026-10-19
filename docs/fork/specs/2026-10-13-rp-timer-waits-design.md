# Gamebots come back worth realm points (design)

Status: approved by the owner, 2026-10-13, as stage 1. The design was approved in conversation; this written spec was
revised after its review and recheck, then the owner answered its open choices (section 9: 1, 2 and 18) and chose to
stage the work: this stage makes released bots wait until they are worth realm points; battleground waves come in a
later stage (Appendix B).
Date: 2026-10-13. Fork: `lometur/HearthDAoC`. Branch: `rp-timer-waits`. Release: merging the PR publishes the next
release; the server picks it up with `./hdc update`, which adds `HEARTHDAOC_BOT_RP_TIMER_WAIT=on` to `.env`. No world
data changes. Part 1 of the RvR bot roadmap, stage 1. Effort: about 3 working days with the in-game check (est.).

References are to HearthDAoC `main` at 5521c75 (v0.35b-hearth.18), `source/server/GameServer/`
unless a path says otherwise. Shorthand: `WBC` = `bots/autonomous/AutonomousWorldBotController.cs`, `BG` =
`bots/autonomous/AutonomousWorldBotController.Battleground.cs`, `FT` =
`bots/autonomous/AutonomousWorldBotController.FrontierThreat.cs`, `GC` =
`bots/autonomous/AutonomousBotGroupCoordinator.cs`, `GRS` = `bots/autonomous/AutonomousGroupRecoveryState.cs`, `ARPR`
= `bots/autonomous/AutonomousBotRealmPointRewards.cs`, `EL` = `bots/autonomous/AutonomousRvrEventLayer.cs`, `ELD` =
`bots/autonomous/AutonomousRvrEventLayer.Defense.cs`, `AOA` = `bots/autonomous/AutonomousObjectiveAssignments.cs`, `GB`
= `bots/GameBot.cs`, `BB` = `bots/BotBrain.cs`. Research: `~/Games/DAoC/research/rvr-bots-2026-10-13/` on the owner's
machine (`README.md` sections 1, 3, 4.1 and 8; `wave-code-map.json`, read at 91ddcf2, where each section's skeptic
"check" wins over its "map"; `source/` is the same at 91ddcf2 and 5521c75). Times marked (est.) are straight lines at
191 units/s, not measurements. The deferred waves' research: `~/Games/DAoC/research/rp-wave-sim-2026-10-13/`
(Appendix B).

## Read this first

**What stays exactly as approved**

- The realm point timer is unchanged: a bot is worth points again 300 s after its last death.
- A released bot waits at a safe spot and leaves so it arrives just as its timer ends. One wait per death.
- A frontier warband leaves together.
- A bot resurrected where it fell fights on, with no wait.
- Waiting bots rest, rebuff, join no new warband, and don't charge enemies they only see, but fight back (except as
  listed below).
- Relic carriers and their escorts never wait.
- One switch, on in HearthDAoC; off gives today's behaviour.

**Where this spec departs from the design** (details in section 1)

- Battleground bots leave one by one, each at its own moment: waves are deferred to a later stage (owner,
  2026-10-13; Appendix B).
- Battleground bots meet enemies again about 300 s after death and reach the central keep at 360-380 s (est.), not a
  round "5 minutes".
- Eight pet classes keep only their main pet up while waiting, no optional buffs, unless a seventh hook is added.
- Invaders, and any bot released in another region than its fight, don't wait.
- Warbands: only members released for their current death hold the warband. Resurrected members don't hold it, but
  walk back and stand at their slots until it leaves.
- A warband that disbands mid-wait ends the wait; its members may go out worth nothing.
- A waiting warband drafted into a battle: its members leave one by one.
- A muster, a battle draft (except a held warband's, which waits on at its slots), a player's invite or a task change
  ends a wait. A fight never does.
- Also never wait: relic interceptors and pickers, relic-event forces, bots in a muster, gamebots in a player's
  group.
- At a bind a waiting bot answers only its own attackers (no threat scan there).
- A siege party can still take a waiting siege member; it keeps waiting.
- A warband can arrive a little early: its leader may pick a nearer target.
- A waiting healer makes its dead group mates lie 90 s, not 20 s, before release.
- A warband member already worth points while its warband waits for a mate charges what it sees.
- One RvR hook, not two; the code is a fork part of the bot controller.

**The owner's answers, 2026-10-13** (section 9)

- The switch: `bot_rp_timer_wait`, set from `HEARTHDAOC_BOT_RP_TIMER_WAIT=on`: approved (choice 1).
- The wave: "which ever is more likely to have bots go in a group", a sliding wave. Then the owner chose to stage the
  work: waves come later, "like during the commander phase and what not" (choice 2, Appendix B).
- Resurrected warband members don't hold the warband ("A, fights on"): approved (choice 18).

**Upstream:** six one-line hooks, as planned. No seventh hook.

## 1. Goal

A gamebot killed in RvR or a battleground comes back to the fight just as it is worth realm points again. The timer
stays exactly as it is.

### What is wrong today

- **The timer.** A gamebot is worth realm points if it has no death on record or 300 s have passed since its last
  one (ARPR:82-86; `rp_worth_seconds`, default 300, `serverproperty/ServerProperties.cs:851-852`). Every death with a
  killer restarts it (ARPR:88-90): a player, an enemy bot, a guard, a pet or a monster (`gameobjects/GameNPC.cs:2949`,
  `serverrules/AbstractServerRules.cs:1038-1041`). It lives only in memory: GB:938 keeps the corpse, so the
  `TempProperties` wipe at `GameNPC.cs:2979-2983` never runs.
- **No bot code reads it.** The key appears only at ARPR:19 (the const), :84 (the reward check) and :90 (the write).
- **Bots release and run straight back.** A corpse releases after 20 s, or 90 s while a living group member in the
  region has a resurrection spell and the power for it (GB:994-999, :1029-1047), polled every 3 s (GB:974). It moves
  to the nearest bind of its realm in that region, else its capital (GB:1076-1090), at a third of its health
  (GB:1095-1097). Solo RvR and battleground bots go back to work on their next turn (WBC:319-324, :533-534, :558-559).
- **Battlegrounds are where it bites.** They have no bindstones, so every death goes to the capital, the realm
  teleporter and back in (BG:43-46, :161-183). Back at the central keep (README 3.3, est.):

| Realm | Back at the central keep | Still worth nothing for |
|---|---|---|
| Albion | about 100 s after death | about 200 s |
| Midgard | about 155 s | about 145 s |
| Hibernia | about 150 s | about 150 s |

- **Frontier.** Defenders release at a home bind; only 7 of the 27 non-portal keeps are within 300 s of one
  (Fensalir Faste 165 s to Dun Lamfhota 279 s, release included; README 3.3 and 8). Invaders release in their capital
  and are almost always worth points again when they arrive. A warband outside a siege battle walks back to its
  border keep and sets out once everyone is back and recovered, with no look at the timer (GC:1908-1932, :1986-1992;
  GRS:45-56).

### Decisions (owner)

- The ask (2026-10-12): "something kind of annoying is that they tend to run out before their rp timer expires, so
  they aren't even worth any realm points. i'd like to keep the timer, but make the bots smarter."
- Roadmap (2026-10-12/13): (1) realm points, this spec; (2) base class and promotion at 5; (3) battleground regulars
  and recycling (#110); (4) RvR groups and keep choice; (5) epic armour; (6) ordinary quests; (7) realm commander. The
  AI bundle, chat and war council are optional but very likely; one model serves all three realms. Each part gets its
  own design, spec, plan and PR.
- "A is my preference": released bots regroup at a safe spot and go back as a wave.
- "A, fights on": bots resurrected in the field fight on, with no wait.
- "A is fine here too": waiting bots rest, rebuff and wait for their wave.
- On the design of sections 2-6 (2026-10-13): "yes that sounds good. proceed".
- On the written spec's choices (2026-10-13): "1. yes approved on the name switch, 2. which ever is more likely to have
  bots go in a group, 3. yes don't hold the warband back." (choices 1, 2 and 18).
- On staging (2026-10-13): "if it makes more sense to do this in stages, and focus more on the bots waiting so they are
  worth rps and then sprinkle in the wave stuff later, like during the commander phase and what not, that will be
  fine." So this spec is stage 1: the waits. Battleground waves are deferred (Appendix B).

### Where this spec departs from the design as presented

The code showed these; each is settled below and can be changed.

- **One RvR hook, not two.** One line after WBC:1736 serves solo roamers and siege members (3.2, 3.3).
- **The waits are a fork part of the controller** (`scripts/hearthdaoc/RpTimerWaitController.cs`, a `partial` of
  `AutonomousWorldBotController`): they need its private movement and status helpers. A new convention; still one
  upstream line per hook (7.3).
- **Eight pet classes don't rebuff while waiting.** Bonedancer, Enchanter, Cabalist, Spiritmaster, Sorcerer,
  Mentalist, Minstrel and Sluaghbinder skip optional buffs whenever they have no camp, which RvR and battleground bots
  never have (`bots/autonomous/AutonomousPetSupport.cs:924-944`; BB:1378-1386, :1414). They keep only a missing
  primary pet up, as today. Fixing that needs a seventh upstream hook, in `BotBrain`, left out.
- **Only bots released in the region of their fight wait.** In the frontier that means defenders and roamers of
  their own frontier, and attackers of a keep in it. Invaders, and attackers of a keep in an enemy frontier, release
  in their capital (`bots/BotReleaseBindPoints.cs:52-70`; GB:1084-1089) and come back as today; they are mostly worth
  points on arrival anyway (README 3.3).
- **Warband members resurrected in the field still go back with their warband.** The existing regroup takes the whole
  warband back to its border keep after any casualty, a resurrection included (GRS:17-19; GC:1873-1906 resumes on the
  spot only for Group PvE). This spec doesn't change that.
- **Their timers don't hold the warband (choice 18).** Only members released for their current death count (3.4).
  A resurrected member walks back with the others and stands at its slot until they leave, but has no wait of its own:
  it charges on sight and fights on, as "A, fights on" says. The existing regroup never reads the timer (GRS:45-56),
  so counting them would be a new wait. The alternative counts them.
- **A warband member worth points while the gate holds charges what it sees.** The gate holds for the released member
  with the most time left (3.4). A member whose own time left runs out while the gate holds for a mate with more time
  left is worth points, so `IsWaiting` is false for it (2.4). It charges on sight as today, and the regroup walks it
  back to its slot (section 4).
- **A warband that disbands mid-wait ends its wait.** Its task clock runs on through the regroup
  (`bots/autonomous/AutonomousGroupTaskClock.cs:5`), so it can expire mid-wait (GC:1684-1690); an unreachable member
  also ends the task (GC:1955-1958). `FinishGroupTask` disbands the group (GC:2351) and gives each member a new
  assignment (GC:2357; AOA:409-431), which ends the wait (2.4). Members may go out worth nothing. Accepted: a task lasts
  45-120 min (`AutonomousGroupTaskClock.cs:18`), a wait about 5 (section 13).
- **A held warband drafted into a battle leaves one by one.** The draft (ELD:254-311) or a member's own pick
  (WBC:474-480) can make a regrouping warband a battle force; GC:1864-1871 then returns before the gate. Its members
  become siege members (3.3) waiting at their slots (3.4).
- **A wait can end before its time** (2.4): the realm calls the bot to a muster, or to a battle other than its own (a
  frontier solo drafted into one, a siege member whose force the draft moves to another keep), a player invites it,
  or its assignment changes. A fight never ends it.
- **"Errs late" holds for battlegrounds and solos, not fully for warbands.** A warband leader may pick a nearer
  target as it sets out (WBC:474-478, :1826-1832), which the coordinator cannot see (3.4).
- **Fighting back also covers a realm-mate, except at a bind.** A waiting bot answers an enemy attacking it or a bot
  or player of its realm within 1,000 of it: the threat scan's own test (FT:113-115). Not at a bind: the scan is off
  inside a bind area (FT:138; WBC:4885-4892). There a frontier solo or siege member answers only enemies attacking it
  (BB:405-433), and a siege-party member also its group mates' attackers (BB:481-520).
- **Battleground sit-out.** A dead bot reaches the first contact point about 300 s after its death and the central
  keep about 360-380 s after (est.), against 100-155 s today: a little more than the "about 5 minutes instead of about
  2" presented, because of the walk past the contact point.
- **No battleground waves in this stage** (owner, 2026-10-13). Each battleground bot leaves at its own moment, as a
  frontier solo does; nothing groups them yet. A later stage adds waves (Appendix B: the owner's choice of a sliding
  wave, the design so far, and what its two reviews found).
- **Every bot chasing a relic never waits, not only escorts.** The design named relic carriers and their escorts. The
  spec also skips interceptors and bots heading for a dropped relic: any bot whose destination is a relic
  (`rvr-relic-carrier-`, WBC:1793-1824; any realm's relic is a target, WBC:2202-2226; "Intercepting relic", :1801). It
  also skips every force of a relic carrier event: the attackers, defenders and third realm of the keep battle the
  relic left (EL:1305-1310) and any force that joins it (EL:1166-1176). Why: the target moves, and the hook runs
  before WBC:1800 and :1812 update it, so the trip would be measured to an old position (frontier missed[4]).
- **Other bots that never wait** (section 5, choice 19): bots in a muster when they release, a warband enrolled in an
  event whose battle has not started (3.4), and gamebots in a player's group.
- **Siege parties may take waiting siege members.** Hook 5 keeps waiting bots out of warbands formed by recruiting
  (3.6). A siege party forming during a battle can still merge them; they wait on (section 4). A filter there would be
  a seventh upstream line, left out.
- **A side effect.** A healer waiting in the same region makes its dead group mates lie 90 s instead of 20 s before
  release (GB:994-995; the check at GB:1034-1039 has no distance limit). Their timers are not changed by it.
- **Siege attackers wait at their frontier muster (added 2026-10-18, the sync to upstream 0.37b).** Upstream 0.37
  releases an attacker of a running siege that has no bind of its realm nearby at its realm's muster for the keep's
  frontier, the portal outpost where its frontier teleporter lands, not in its capital (`bots/GameBot.cs:1100-1105`,
  `AutonomousRvrEventLayer.TrySiegeRelease`, `AutonomousRvrStaging.TryGetSiegeMuster`, at the merge). Its first look
  is then in the region of its fight, so it waits there as a siege member (3.3, `start case=siege`), or goes at once
  when the walk to the keep is longer than its time left (`skip reason=trip`): most do, since with a healer of its
  army near it now lies 240 s before it releases (`bots/GameBot.cs:1000-1003`). No code changes: the rule already
  lets a siege member wait. Where this spec says attackers of a keep in an enemy frontier release in their capital and
  never wait (the bullet "Only bots released in the region of their fight wait", 2.5's "Siege attacker" row, 3.3,
  section 5), that was upstream 0.35b; other invaders still release in their capital and skip with `other-region`.

## 2. The rule

After a bot releases, it waits at a safe spot. It leaves when its time left is no more than its trip back to the
fight, so it arrives just as it is worth realm points again. One wait per death.

### 2.1 Time left

`RpTimerWait.WorthlessForMilliseconds` mirrors the reward check at ARPR:82-86 exactly:

- `last` = the bot's `TempProperties["autonomous.rvr.last.realm.point.death.tick"]`, -1 if none (ARPR:19, :83-84),
  in `GameLoop.GameLoopTime` (ARPR:82).
- `interval` = `max(0, rp_worth_seconds) × 1000` (ARPR:85).
- Time left = 0 if `last < 0` or `interval = 0`; else `interval − (now − last)`, kept within 0 to `interval`.
- So time left is 0 exactly when ARPR:86 says "worth" (`now − last >= interval`).

The fork reads the `internal` key const directly: `scripts/hearthdaoc` compiles into the same GameServer assembly (BG:37
calls into it). ARPR is not changed.

### 2.2 Trip

- A straight line from the bot's waiting spot to its target (section 3 names the target per case), divided by its
  best speed. A walked path is never shorter, so the bot errs toward arriving a few seconds late.
- **Best speed** = the largest of: its live `MaxSpeed`; its `MaxSpeedBase` (191: GB:2327,
  `gameobjects/GamePlayer.cs:8209`); and `MaxSpeedBase × v / 100`, where `v` is the highest speed-enhancement value
  among its own spells at or under its level, in the pool its song upkeep casts from (`MiscSpells`,
  `InstantMiscSpells`: BB:2177-2185; the effect applies `Value / 100`, `ECS-Effects/SpeedEnhancementECSEffect.cs:20`).
  Why: `MaxSpeed` drops below 33% health and a released bot starts at a third
  (`propertycalc/MaxSpeedCalculator.cs:140-143`; GB:1095); a Minstrel, Skald or Bard starts its speed song only once
  it moves (BB:2172-2175), so a live reading while standing is too slow.
- No porter or teleporter time is modelled: a bot in another region than its target never waits (3.2).

### 2.3 Wait or go

- Wait while time left > trip. Leave on the first turn where time left ≤ trip.
- Battlegrounds too, in this stage: each bot leaves at its own moment; nothing groups them (waves: Appendix B).
- Recomputed every turn from the timer, the spot and the target; nothing is cached across deaths.
- **A standing bot thinks only every few seconds.** Its Planning interval is 2.5 s
  (`bots/autonomous/AutonomousAiBudget.cs:29`), ×1 with a player within 6,000, ×1.6 when none is that near but a player
  was sent an update of it in the last 60 s, and ×2.6 when none was (BB:2626-2640, rechecked every 5-6.5 s;
  `gameobjects/GameNPC.cs:36`, :692), then × up to 1.6 at 1,500 bots or more
  (`bots/autonomous/AutonomousFidelityPolicy.cs:51-58`), plus a stagger under an eighth (:69-76): at most about 7.3 s at
  300 bots or fewer, and about 11.7 s at 1,500 or more.
- **So the wait wakes the bot at its leave moment.** It sets the next think to the leave moment when that is sooner than
  the standard one (at least 250 ms), as `bots/autonomous/AutonomousWorldBotController.KeepTravel.cs:86` does; the next
  think is then due at now + that interval (`ECS-Services/NpcService.cs:84`). It adds half a game tick, rounded up (17
  ms at 30 ticks/s), because a brain may think up to half a tick early (`ECS-Services/GameServiceUtils.cs:22`), and a
  think just before the moment would hold and come back only 250 ms later.
- **The wake covers one think.** A think that reaches the controller has first set the standard interval again
  (BB:1335-1338, before Tick at BB:1482), so each hook turn sets its wake afresh. The woken think reaches the hook only
  if nothing earlier takes the turn: a fight the threat scan starts (BB:1254-1259) or one already running (WBC:368-393),
  a cast still running (WBC:442-443), a rebuff (BB:1414-1416), pet upkeep (BB:1455-1458) or a self bladeturn
  (BB:1315-1316; it returns before BB:1335, so that think keeps the wake interval). Songs never take it: every classic
  song is cast on the move, so BB:2255 gives the turn back. A bot whose woken think is taken leaves at its next hook
  turn: its next think comes up to one standard interval later, and each further taken turn adds up to one more; a fight
  holds it until 10 s after the last blow (WBC:368-393; `gameobjects/GameLiving.cs:31`). Late, the safe side. At a quiet
  spot this is rare.

### 2.4 The marker, the one-wait latch, and what counts as waiting

- **The marker:** kept in one fork `TempProperty` per bot (`hearthdaoc.rp.wait`, a holder, 7.2). It holds the death
  count it is for (`PersistentRecord.DeathCount`, raised at every death, GB:953), a phase (Released, Waiting, Left),
  the case (battleground, frontier, siege, warband), the release region and point, the region and spot of the wait,
  the bot's `PersistentRecord.ObjectiveAssignmentId` (written at AOA:525, :503, :641), the warband's session id
  (warbands only), the event keep id (sieges only: `_rvrDestination.Id` at wait start or at Convert, 3.3, 3.4), and
  when the wait started (for the log). Nothing in it ages: there is no hook-turn stamp. It is never changed in place:
  every write swaps in a new marker by compare-and-set (7.2).
- **Released:** set by hook 3 (3.5) on the first controller turn after a release, when the bot is alive,
  `IsReturningAfterRelease` is still true and its goal is RvR or Battleground. Only a release sets that flag
  (GB:1098); the hand-over right after the hook clears it (WBC:323-324; GB:1187-1197); a resurrection clears it with
  no release (GB:1126). It stores the release region, the release point and the assignment id.
- **Waiting:** set when a wait starts, by a first look in hooks 1-2 (3.1-3.3) or by the warband gate (3.4). It
  stores the case, the region and spot, the assignment id at that moment, and for a siege the event keep id.
- **Left (the latch):** set when the wait ends, or when the first look finds no wait needed or a reason not to wait,
  or at the bot's next death (3.7).
  While the marker is Left for the current death count, no hook stops the bot again, whatever its speed or
  destination does next.
- **What ends a wait.** Each latches Left by one successful swap and logs one `leave` with its reason (10.5, 7.2):
  - its time: hooks 1-2 (`due`), or the warband gate opening (`due`, 3.4);
  - its assignment id changes, or it is in another region than its wait (`changed`, hook 3). A new goal, a task that
    ends, a battleground tour that ends and a siege event that releases its solo force all write a new id
    (AOA:409-431, :434-445, :641; WBC:233-237);
  - the realm calls it (`called`): a frontier solo whose force joins any event (a muster, a battle draft, a relic
    event), or a siege or warband member whose force gets a muster order (hook 3, 3.5); or a siege member (a drafted
    warband member too) whose force the draft moves to another event: hook 2 sees another keep than the stored one
    (ELD:294-307; with no muster order when the new defence is already marching or the force is an ally, ELD:309-310;
    3.3);
  - a player invites it into a group (`player-group`, 3.8);
  - a warband marker on a bot no longer in a group (`changed`, hook 3);
  - a case change seen by hooks 1-2 (`changed`), except a held warband drafted into a battle (3.4: `battle`, then a new
    `start` as a siege member);
  - a relic, a target gone, or a target in another region (`relic`, `no-target`, `other-region`, hooks 1-2);
  - the switch turned off (`off`, hook 3, section 6);
  - a new death (`died`): the `Dying` handler (3.7) latches a Waiting marker Left as the death ends, whether the bot
    is then released or resurrected.
- **A fight never ends a wait.** The bot fights back (section 4). Afterwards its marker is still Waiting, and the hook
  walks it back to its spot, however far and however long the fight took it.
- **Counts as waiting** (`IsWaiting`, read by hooks 5 and 6). From the marker and cheap reads of the bot only, with no
  clock. All of:
  - the switch is on, the marker is for the current death count, and time left > 0;
  - the bot's assignment id is the stored one, and it is not in a player's group (`IsPlayerLedGroup`, GB:40);
  - and either the marker is Waiting, the bot is in the stored region, and (warband case) it is still in a group;
  - or the marker is Released (its first look is still to come) and the bot stands where that first look will happen:
    in a battleground region (250-253) within 2,500 of its realm's `BotArrival` there
    (`world/BattlegroundBrackets.cs:29`, :51-56, :95-101), or in its release region, when that is a frontier region
    (1, 100 or 200), within 750 of its release point. A frontier invader releases in its capital (10, 101 or 201), so
    a Released invader never counts, in its capital or in the frontier.
- **Companions:** a persistent gamebot never becomes a `/spawn` or `/raid` companion. Those are separate helper bots:
  `IsTemporaryGroupHelper` is set only by the helper constructor (GB:2232); persistent bots are built at GB:2297-2310.
  A player's group is the only companion role a gamebot takes (3.8).
- **What resets it:** only a new release after a new death (a higher death count). A resurrection does not (no
  release). A server restart clears it, with the timer (both memory only).
- A marker for an older death count is ignored, and the `Dying` handler has already latched it Left (3.7). So a bot
  that dies again and is resurrected never inherits the old "released" or the old wait.

### 2.5 Worked examples (est.)

Death at t = 0; straight lines at 191 units/s.

| Case | Bot | At its spot | Time left there | Trip | Leaves at | At the fight |
|---|---|---|---|---|---|---|
| Battleground | Albion, Thidranki, killed near the central keep | arrival point at ~30 s (release ~21 s, teleporter 6 s) | ~270 s | 2,147 → 11 s | 289 s | first contact 300 s; central keep about 60 s later |
| Battleground | Midgard (Hibernia alike) | ~30 s | ~270 s | 8,181 → 43 s | 257 s | first contact 300 s; central keep 80 s later |
| Frontier, alone | Midgard defender bound for Fensalir Faste | home bind at ~21 s | ~279 s | 145 s | 155 s | 300 s |
| Siege member | Hibernian defender of Dun Ailinne, solo | home bind at ~21 s | ~279 s | 229 s | 71 s | 300 s |
| Siege member | the same, with a living group healer in the region | home bind at 90 s | 210 s | 229 s | at once (no wait) | 319 s |
| Siege attacker | Albion at a keep in Midgard's frontier | capital at ~21 s | ~279 s | other region | at once (no wait) | 7 min or more: worth |
| Frontier warband | Albion, 3 of 8 die 6,000 from Castle Sauvage and release | slots at ~110 s (release at 90 s) | ~190 s (latest death) | 6,000 → 31 s | gate opens at 269 s, 5 s settle: 274 s | ~305 s |

## 3. Where bots wait, and the hooks

### 3.1 Battlegrounds

- **Who:** a released bot on its battleground tour, back inside its bracket's region. Battleground bots are always
  solo: groups form only for Group PvE and RvR (GC:1437-1441).
- **Spot:** its realm's arrival point, `BattlegroundBrackets.BotArrival` (`world/BattlegroundBrackets.cs:95-101`):
  field mesh about 800 outside the portal keep's gate, the same in all four battlegrounds. Not the portal keep: bots
  cannot path out of it (:89-94). Each bot takes slot `1 + ObjectID % 12` of `AutonomousTownTeleporters.Arrival`
  (`bots/autonomous/AutonomousTownTeleporters.cs:143-163`), 160-330 from the point, snapped to the mesh. Waiting bots
  stand apart, at or near the 400 exit radius (BG:22, :209-210).
- **First look:** the bot must be within 2,500 of `BotArrival`. The teleporter lands it at slot 0
  (`bots/autonomous/AutonomousWorldBotController.TownTeleport.cs:139-152`). Farther away, no wait (latched).
- **Before the first look:** the threat scan runs before the controller (BB:1254 before :1482), so on its first think
  inside it would run before hook 1. The Released marker already counts as waiting there (2.4), so the bot doesn't
  charge an enemy it only sees before hook 1 starts its wait.
- **Trip target, the first contact point.** Enemy roamers patrol anchors 0.6 of the way from each other realm's
  arrival point to the central keep (BG:121-127), within 900 of the anchor (BG:135), and their threat scan reaches
  5,000 (WBC:35; FT:151-157). So the nearest place an enemy patrol can engage a bot of realm R is on the line from R's
  arrival point A to the central keep C, at `0.6 × |AC| − 900 − 5,000` from A (never below 0). The trip is from the
  bot's spot to that point.

| Realm | Arrival to central keep | First contact from the arrival | Trip at 191 |
|---|---|---|---|
| Albion | 13,411 | 2,147 | 11 s |
| Midgard | 23,468 | 8,181 | 43 s |
| Hibernia | 23,388 | 8,133 | 43 s |

  Measured to the central keep instead (70, 123 and 122 s), a bot could meet enemies with up to about 54-75 s still on
  its timer (battlegrounds check, missed[0]).
- **Leaves:** when time left ≤ trip, at its own moment (2.3). In this stage nothing groups battleground bots; waves
  come later (choice 2, Appendix B).
- **Hook:** BG:67-72 today:

  ```csharp
  _rvrSharedEvent = false;
  _rvrIntent = assault ? AutonomousRvrEventLayer.Intent.AssaultKeep : AutonomousRvrEventLayer.Intent.Roam;

  if (assault)
  {
      if (TryRunSiegeJob(bot)) return true;
  ```

  Added after line 68:

  ```csharp
  // HearthDAoC: back from a death and worth no realm points yet: wait at the arrival point.
  if (RpTimerWaitBattleground(brain, bot, bracket, central)) return true;
  ```

- **Why there:** after the over-cap check (BG:37-42) and the region check (BG:43-47), so only bots inside their
  battleground; before the siege job (:72), the assault (:73-99), the defence (:103-109) and the roam (:110), so every
  role waits. Returning true skips `FSM.Think` (BB:1482-1496). It adds no `TravelToBattleground(` and no
  `ClassicBattlegroundsScript` call, so `deploy/tests/test_battlegrounds.py:160-192` stays as it is.

### 3.2 Frontier, alone

- **Who:** a released solo RvR bot (no warband) in the same region as its target. In practice a defender or roamer of
  its own frontier: the nearest bind of its realm lies in its own frontier region (`bots/BotReleaseBindPoints.cs:29-30`,
  :52-70). Invaders release in their capital (GB:1084-1089), another region, and never wait: their trip is the
  capital, the border keep, up to 120 s for the Old Frontiers porter, then 237-969 s on foot (README 3.3 and 8).
- **Spot:** its release point, the bind stone. Enemy bots never pick a target inside a bind area
  (`bots/autonomous/AutonomousRvrTargetPolicy.cs:5-8`, called at FT:147-149; bind areas count as safe, WBC:4885-4892),
  and its own scan is off there (FT:138). Bind areas have radius 750 in the clean 0.35 world. Border keeps are not
  safe areas (their area rows are plain circles: frontier check, corrections[0]), so the bind is the spot, not the
  border keep.
- **First look:** within 750 of the release point, in its region. Otherwise no wait (latched): `skip
  reason=other-region` when the bot is in another region than its release point or its target (an invader arriving
  from its capital), `moved-away` when it is farther than 750. A marker already Waiting skips the first look: the hook
  checks the case, region and assignment are unchanged (2.4) and holds.
- **Trip target:** its current destination (`_rvrDestination`) when that is in its region; else where it died (3.7)
  when that is; else no wait.
- **Leaves:** when time left ≤ trip. On leaving, its destination is kept until it is worth points again
  (`_nextRvrPlanReview` is pushed to that moment). Otherwise the re-pick at WBC:1826-1832, whose review time has long
  passed, could choose a nearer target and it would arrive early (frontier check, corrections[2]).
- **Called away:** if its force joins any event while it waits (a muster, a battle draft, a relic event), hook 3 ends
  the wait (`called`, 3.5). It goes where the realm sends it, possibly worth nothing (choice 20).
- **Hook:** ExecuteRvr, WBC:1729-1740 today:

  ```csharp
  if (_rvrSharedEvent && _rvrDestination != null &&
      !AutonomousRvrEventLayer.IsTargetActive(_rvrDestination.Id, GameLoop.GameLoopTime))
  {
      _rvrDestination = null;
      _rvrApproachDestination = null;
      _rvrSharedEvent = false;
      _nextRvrPlanReview = 0;
  }

  // RvR has no PvE puller. Every cohesive member can acquire a local
  // target, with pressure spread over the closest visible enemies.
  if (TryRunSiegeJob(bot)) return true;
  ```

  Added after line 1736:

  ```csharp
  // HearthDAoC: back from a death and worth no realm points yet: wait at the bind.
  if (RpTimerWaitRvr(brain, bot, battleActive, dynamicWarband, committedPlan != null)) return true;
  ```

- **The case it sees:** `battleActive` with a keep plan is a siege (3.3); `battleActive` without one is a relic event
  (never waits, section 5); `dynamicWarband` outside battle is a warband (the gate's, 3.4; this hook doesn't start
  one); anything else is frontier alone.
- **Why there:** after the rally and muster orders (WBC:1712-1717: a muster is a wait already), the warband pull hold
  (:1721) and the solo staging gate (:1723-1724); after the stale-target clear (:1729-1736), so a finished event is not
  measured; before the siege job (:1740), the target search (:1741), the relic branches (:1772-1824) and the re-pick
  (:1826-1842), so nothing moves or re-tasks the bot while it waits. Solo roamers reach it from WBC:533-534, battle
  forces from :479-480. The design named "~1724/1737"; one site serves 3.2 and 3.3.

### 3.3 Siege-battle members

- **Who:** a released member of a force in a started keep battle (`battleActive`, WBC:1697) with a keep plan
  (`committedPlan`, :1698-1711), solo or in a warband (in battle members return one by one, GC:1865-1872). A relic
  battle counts as a battle with no keep plan (EL:766 against :769-778) and never waits.
- In practice: the realm whose home frontier holds the keep, defending or retaking it. Its bots release at a home bind
  in that region (siege check, corrections[0]). Attackers of a keep in an enemy frontier release in their capital and
  never wait.
- **Spot and first look:** as 3.2, with one exception: a member of a held warband drafted into the battle waits at
  its regroup slot (3.4, "Drafted mid-wait").
- **Trip target:** the event keep, which ExecuteRvr writes into `_rvrDestination` at WBC:1706-1707. Its id is
  stored in the marker at wait start.
- **Leaves:** when time left ≤ trip. A defender whose bind is within 3,500 of the keep goes straight to its post with
  no walk (WBC:1880-1882), so its trip is near 0 and it waits nearly the whole timer within sight of the fight. That is
  the rule working (siege check, missed[9]).
- **Called away:** a player-triggered defence can give its defenders muster orders although the battle is on
  (EL:725-752). A waiting siege member whose force gets one stops waiting (`called`, 3.5). The draft can also move a
  defence force to another defence (ELD:294-307). With or without a muster, that ends the wait: hook 2 sees another
  keep in `_rvrDestination` than the one stored at wait start (`called`). Hook 3 can't see the move when there is no
  muster order (the new defence already marching, or an allied force: ELD:309-310; EL:733-735), and
  `IsForceCommitted` stays true, so hook 2 makes this check (choice 20).
- **Event ends:** its solo force is released (WBC:233-237) and gets a new assignment, which ends the wait (2.4).
- **Hook:** the same line as 3.2. At wait start the fork frees the bot's siege job (`ReleaseSiegeJob`,
  `bots/autonomous/AutonomousWorldBotController.Siege.cs:465-472`): its slot lease would otherwise hold a ram or engine
  from other crews for up to 120 s (`bots/autonomous/AutonomousSiegeJobs.cs:40-78`). After the wait `_siegeJobKeep` is
  null (Siege.cs:469), so `TryRunSiegeJob`'s walk-back (Siege.cs:83-85) does not fire. The bot goes back by ExecuteRvr's
  ordinary travel (WBC:1868-1900; a defender by `TravelToDefensivePost` or `HoldDefensiveKeepPost`, :1878-1882). Within
  6,000 of the keep it takes a fresh siege job (Siege.cs:86-107).

### 3.4 Frontier warbands

- **Who:** an RvR warband regrouping after a casualty, outside a siege battle (GC:1908-1932). Any casualty sends the
  whole warband back to the border-keep slots chosen when it formed (GC:2549-2556).
- **Only RvR sessions.** A Group PvE party reaches the same completion after a wipe (GC:1873-1907), and a monster kill
  restarts the timer too (ARPR:88-90). So for any other objective kind the gate says go at once and writes nothing.
  Group PvE never waits. With the switch off it says go at once and writes nothing too (section 6).
- **Not in a muster.** A warband in an event whose battle has not started still regroups after a casualty:
  GC:1864-1871 skips only battle forces (EL:761-767), and its members go to the regroup (WBC:479-484), not to the
  muster. So the gate also says go at once and writes nothing when `IsForceCommitted(session.Id)` (EL:1235-1245) is
  true, as GC:1686-1687 reads it under this lock. Hook 3 ends the wait of any member already Waiting (`called`, 3.5).
- **Who holds it:** members released for their current death (marker Released or Waiting for it, 2.4). A member
  resurrected in the field has no marker for its current death and doesn't hold it (choice 18). It still walks back
  and stands at its slot with the rest, because the regroup takes the whole warband back after any casualty
  (GRS:17-19). It gets no Waiting marker, so it charges on sight as today: it fights on.
- **Spot:** each member's slot, `RendezvousFormationPoint` (GC:1148-1160), where it already stands "Formed up at
  rendezvous" (WBC:1461-1477).
- **Markers while the gate holds:** on each pass where it holds, the gate turns the Released marker of each member that
  stands in the rendezvous region, for its current death, into Waiting: case warband, spot = its slot, region = the
  rendezvous region, its current assignment id, and the session id. A marker already Waiting is not written again. A
  member still in another region (released to its capital) stays Released and still holds the gate; it turns Waiting on
  the first pass after it enters the region. The gate only changes Released to Waiting while it holds, and Waiting or
  Released to Left when it opens. It never writes over a Left marker (7.2). So `IsWaiting` is true for the Waiting
  members while their own time left > 0, and hooks 5 and 6 apply (section 4). The gate does no controller work: the
  regroup itself stops members at their slots, rests them and walks them back after a fight (WBC:1436-1477).
- **Leaves:** together, once the released member with the most time left can make the march: the gate holds while
  that time left > the march. Then `TryComplete` adds its 5 s settle (GRS:12, :45-56).
- **March:** a straight line from the rendezvous to where that member died (3.7), at the fastest member's best speed.
  No wait if that spot is in another region than the rendezvous (an invasion), or no death record matches its death
  count.
- **Never** with a relic carrier in the party (`GameRelic.IsPlayerCarryingRelic`, `keeps/Relics/GameRelic.cs:460`).
- **Hook:** GC:1986-1987 today:

  ```csharp
  if (session.LeaderReadyForAssembly &&
      session.Recovery.TryComplete(RecoveryMembers(session, members, true), GameLoop.GameLoopTime))
  ```

  becomes:

  ```csharp
  if (session.LeaderReadyForAssembly &&
      // HearthDAoC: the warband leaves together once its member with the most time left can make the march.
      !HearthDAoC.RpTimerWaitScript.WarbandWaits(session.Id, session.ObjectiveKind, session.RendezvousRegion, session.Rendezvous, members) &&
      session.Recovery.TryComplete(RecoveryMembers(session, members, true), GameLoop.GameLoopTime))
  ```

- **Why there:** before `TryComplete`, so the regroup stays open: members stay at their slots, keep the status
  "Formed up at rendezvous" that the stuck watchdog exempts (`bots/autonomous/AutonomousStuckWatchdog.cs:404-405`),
  start no new pull, and leave as one. It runs at most once a second per party (GC:1963-1965), under the coordinator
  lock (GC:212), so it does only timer reads, one `IsForceCommitted` read (as GC:1686-1687), arithmetic, marker swaps
  and one log line per change: no I/O beyond the log, no `IsSafeArea`. `RendezvousFormationPoint` takes the same lock
  (GC:1150-1157); it is a plain `lock` (GC:35), which the same thread may take again. The follower path (WBC:1758)
  is not the place: outside sieges a released member never reaches it before the regroup (README 8).
- **With the switch on, when the gate opens or finds nothing to wait for:** every member's marker for its current
  death is latched Left, unless it is Left already. A Waiting one logs `leave reason=due`; a Released one still worth
  nothing logs `skip reason=trip`. A marker for an older death is already Left (3.7). With the switch off, a non-RvR
  session or a committed force, the gate says go and writes nothing (above; section 6).
- **Logs:** one `start case=warband group=<session id>` per member, at the swap that turns its marker Waiting (not on
  later passes); one `leave` per Waiting member when the gate opens. A swap the gate loses logs nothing (7.2).
- **Disbanded mid-wait:** the wait ends. Task expiry (GC:1684-1690) or an unreachable member (GC:1955-1958) runs
  `FinishGroupTask`, which disbands the group and gives each member a new assignment (GC:2351-2357; AOA:409-431). On
  each member's next controller turn hook 3 latches it Left (`leave reason=changed`). A member with a new RvR goal
  walks out as a solo, possibly worth nothing. Accepted (section 13). Any other way out of the group leaves a
  warband marker without a group, which hook 3 ends the same way.
- **Drafted mid-wait:** if the session becomes a battle force while the gate holds (the draft, ELD:254-311; or a
  level-50 member's pick at WBC:474-477 joins a battle), GC:1864-1871 returns "Siege in progress" before the gate, and
  members go to ExecuteRvr (WBC:479-480). If that battle musters its defenders first (a player-triggered defence,
  ELD:309-310; EL:725-752), the muster calls them away instead (`called`, 3.5). Otherwise hook 2 sees a siege (3.3)
  and a Waiting warband marker. Its first look as a siege member accepts the slot: in the stored region, within 200
  of the stored spot (the `RendezvousFormationPoint` the gate stored). It logs `leave reason=battle` for the warband
  wait and `start case=siege` with the same `group=`, and stores the event keep id. Then it follows 3.3: each member
  leaves on its own when its time left ≤ its trip to the event keep, and a later draft to another keep ends the wait
  (`called`, 3.3). Farther than 200 from its slot, or with time left ≤ that trip already: `leave` (`moved-away` or
  `due`), latched, and it goes in as today. A member whose marker is still Released (the gate had not held it yet, or
  it was in another region) gets the plain 3.3 first look at its bind.
- **Joins a muster mid-wait:** a level-50 member's pick (WBC:474-477) can enrol the warband in an event whose battle
  has not started. It is no battle force yet, so its members keep regrouping (WBC:482-484). But their force now has a
  muster order, so hook 3 ends each member's wait (`called`, 3.5). The gate then says go at once and writes nothing
  (Not in a muster, above), and the warband goes to the muster, which is a wait already (WBC:1712-1717).

### 3.5 Hook 3: the release note, and the end of a wait

- **Hook:** WBC:319-324 today:

  ```csharp
  ObserveDeaths(bot);

  // Every autonomous return uses the same navmesh controller,
  // even before a casualty has propagated into group metadata.
  if (!bot.IsPlayerLedGroup)
      bot.HandOverReleaseReturnToGroup();
  ```

  Added after line 319:

  ```csharp
  // HearthDAoC: note a release (not a resurrection) before the hand-over clears it.
  HearthDAoC.RpTimerWaitScript.NoteRelease(bot);
  ```

- **What it does,** on every controller turn of a gamebot that is not player-led:
  - Reads the release flag and the marker (one dictionary read). A bot with neither costs nothing more.
  - **A release:** if the switch is on and its goal is RvR or Battleground, it writes Released for the current death
    (2.4), over any older death's marker, which the `Dying` handler has already latched Left (3.7).
  - **A Waiting marker for the current death:** it ends the wait (2.4) when the switch is off (`off`); the assignment
    id or region changed, or a warband marker has no group (`changed`); or the realm called the bot (`called`). Called
    means: a frontier solo whose force is now committed to an event (`IsForceCommitted`, EL:1235-1245), or a siege or
    warband member whose force has a muster order (`GetRallyOrder`, EL:725-752). The force is the stored session id
    for a warband marker; otherwise the one ExecuteRvr last recorded, `RvrEventForce`, else `rvr-<id>`, as
    `bots/autonomous/AutonomousFrontierTransport.cs:86` reads it. A siege member moved to another keep with no muster
    order is hook 2's to end (3.3).
  - Otherwise nothing.
- **Why there:** the last place where "released" is still readable (2.4). It is also before the rally return
  (WBC:1717), which hook 2 never sees. Before line 323, not between 323 and 324: line 323 is an `if` with no braces
  (siege check, corrections[3]). After the return at WBC:226-227, so companions and player-led bots never get a marker.
- **Cost:** for a bot with no marker that is not returning, two field reads and one dictionary read. The event-layer
  calls run only for a waiting frontier, siege or warband bot. ExecuteRvr makes the same calls every turn for every
  RvR bot (WBC:1697, :1712; GC:1482 under the coordinator lock), so they add no new kind of work. `GetRallyOrder`
  reserves rally slots for a force (EL:741-746), the same reservation WBC:1712 makes on that turn.
- **No controller work.** A wait that hook 3 ends is taken over by the goal reset (WBC:245-279) or the muster's own
  routing (WBC:1717).

### 3.6 No recruiting of waiting bots

- **Hook:** the recruiting filter of `TryFormGroups`, GC:1478-1480 today:

  ```csharp
  GameBot[] available = activeRoster
      .Where(bot => bot.IsAlive && !bot.IsTemporaryGroupHelper && !bot.IsPlayerLedGroup && bot.Group == null && bot.CurrentRegion != null &&
                    !AutonomousRealmRaid.IsReserved(bot) &&
  ```

  Added after line 1480:

  ```csharp
                    // HearthDAoC: a bot waiting out the realm point timer joins no new roaming warband.
                    !HearthDAoC.RpTimerWaitScript.IsWaiting(bot) &&
  ```

- **Why:** every 15 s it takes any living ungrouped RvR bot (GC:1448-1450, :1478-1487) and makes the ones nearest the
  border keep leaders (GC:1495-1504); a new warband's assembly marches out with no timer check (GC:1995-2007).
- **Where it stops:** siege parties are formed separately (`FormSiegeParties`, GC:184;
  `bots/autonomous/AutonomousBotGroupCoordinator.SiegeParties.cs:31-35`, no wait filter) and may take a waiting siege
  member. It keeps waiting (section 4). No hook covers that; a filter there would be a seventh upstream line.

### 3.7 The `Dying` handler: the death record, and the end of a wait (no upstream line)

- A fork handler of `GameLivingEvent.Dying`, added at script load as `scripts/hearthdaoc/LinkedCamps.cs:59-61` adds
  its handler, records for each persistent gamebot (`hearthdaoc.rp.death`): its death count, region, position and
  timer value. `Dying` fires at the end of a death (`gameobjects/GameLiving.cs:2073`), after the death count (GB:953)
  and the timer (ARPR:90) are written. It runs with the switch on or off (section 6).
- Used by the warband march (3.4), by the solo trip when the bot has no destination (3.2), and by the log (10.5).
  `GameBot._deathLocation` is private (GB:99).
- **It also ends a running wait** (`Died`, 7.1). The death count was raised at GB:953 before `Dying` fires, so the
  bot's marker is now for an older death count. A Waiting one is latched Left and logs `leave reason=died`. This
  happens at any death, a monster kill included, with the switch on or off. A Released one has no `start`: it is
  latched Left with no line, so a gate or hook 1-2 swap that read it before the death fails (7.2). Either way the
  marker is then ignored (2.4).
- So a bot killed while waiting and then resurrected (GB:1121-1126; by a group healer, BB:5145, or a player,
  `spells/ResurrectSpellHandler.cs:164-165`) gets its one `leave` at its death and no new marker. It fights on. A bot
  released instead gets a new Released marker from hook 3 (3.5).
- The handler has no next turn, so a swap it loses is read again and retried until it succeeds or nothing is left to
  write (7.2).

### 3.8 The player-group handler (no upstream line)

- A fork handler of `GroupEvent.MemberJoined` (`gameutils/Group.cs:193`), added at script load like the `Dying`
  handler. When a gamebot with a Released or Waiting marker for its current death joins a group whose leader is a
  player (`Group.Leader`, Group.cs:58-61), the marker is latched Left. A Waiting one logs `leave reason=player-group`.
  Like the `Dying` handler, it retries a swap it loses (7.2).
- A player's invite builds such a group (`bots/BotGroupInvite.cs:39-46`). A siege party's leader is a bot
  (SiegeParties.cs:59), so a merge doesn't end a wait.
- **Why:** no hook sees a player-led bot. Tick, the threat scan and recruiting all return first for it (WBC:226-227;
  FT:133; GC:1479). While it is in the player's group `IsWaiting` is false (2.4); without the latch, a bot the player
  drops within its timer would walk back to its old spot.

## 4. While waiting

- **Stands still** at its spot (`StopMovingOnPath`, `StopMoving`). More than 200 from it (after a fight), it walks
  back, from any distance: a fight never ends a wait (2.4). In a warband the regroup walks it back to its slot.
- **Regenerates normally:** at least 10% a second out of combat (`bots/BotRestRecovery.cs:26-27`, :68-80). No
  `BeginRecoveryRest`: Tick wakes recovery rest every turn before these hooks (WBC:437-440), and `BeginRecoveryRest`
  cancels casts and attacks (GB:2455-2477), so it would toggle each turn and block rebuffing. Warbands keep the
  regroup's own rest at the slot (WBC:1470-1474), which Tick doesn't wake during "Regrouping" (WBC:438-439).
- **Keeps buffs and pets up:** the brain's upkeep runs before the controller (BB:1413-1416, :1455-1459). The eight
  movement-first pet classes keep only a missing primary pet up (section 1, departures).
- **Joins no new roaming warband** (3.6). A waiting siege member can still be merged into a siege party of its own
  battle (SiegeParties.cs:31-35, every 10 s). It keeps waiting: the merge changes neither its assignment, region,
  case nor event keep, the party's leader is a bot (3.8), and in battle each member returns on its own (the follow at
  WBC:1758 runs only outside battle), so hook 2 still holds it.
- **Doesn't charge what it only sees, but fights back.** The threat scan runs before the controller (BB:1251-1261) and
  charges any enemy bot, player or player pet in sight within 5,000 (FT:126-201; WBC:35). Hook, FT:151-158 today:

  ```csharp
  GameLiving[] nearby = bot.GetPlayersInRadius(TargetSearchRadius).Where(Eligible).Cast<GameLiving>()
      .Concat(bot.GetNPCsInRadius(TargetSearchRadius)
          ...
      .Where(target => bot.GetDistanceTo(target) <= TargetSearchRadius)
      .Where(target => defending || !BotSiegeRuntime.Assigned(bot) || bot.IsWithinRadius(target, 450) && target is not GameSiegeWeapon)
  ```

  Added after line 157:

  ```csharp
      // HearthDAoC: a bot waiting out the realm point timer answers only enemies attacking it or a realm-mate near it.
      .Where(target => !HearthDAoC.RpTimerWaitScript.IsWaiting(bot) || FiringOnRealm(bot, target))
  ```

  `FiringOnRealm` (FT:113-115) is the scan's own test: the enemy is attacking or casting at this bot, or at one of its
  realm within 1,000. An enemy that hits the bot also gives it aggro, and Tick's combat branch hands it to the fight
  (WBC:368-393). After the fight the hook walks it back, and it waits on: its marker is still Waiting.
- **Holds through fights.** `IsWaiting` has no clock (2.4). The turns a bot spends fighting (WBC:368-393, and 10 s
  after the last blow, `GameLiving.cs:31`), casting (WBC:442-443) or rebuffing (BB:1414-1416) never reach the hooks,
  yet the no-charge and no-recruiting rules hold through them.
- **Worth points but still held:** a warband member whose own time left runs out while the gate holds for a mate with
  more time left is worth points. `IsWaiting` is then false (2.4), so it charges what it sees, as today, and the
  regroup walks it back to its slot. Battleground, frontier and siege bots are never held for a mate: each leaves at its
  own moment, when time left ≤ trip, so normally while time left > 0. One is worth points before it leaves only if it
  leaves late: a fight runs past its moment (a fight never ends a wait), or its woken think is taken and its next hook
  turn comes more than its trip later (2.3). That needs a short trip: an Albion battleground bot (about 11 s, 3.1) or a
  siege defender whose bind is near its keep (3.3). `IsWaiting` is then false for it too, so it charges what it sees, as
  today, and it leaves on its next hook turn.
- **Where hook 6 matters:** at battleground arrival points and warband slots (border keeps are not safe areas, 3.2).
  At a bind the scan returns before this filter (FT:138). There a waiting frontier solo or siege member answers only
  enemies attacking it (BB:405-433), and a siege-party member its group mates' attackers too (BB:481-520). It does not
  defend other realm-mates: a limit (section 13).
- **Resurrected warband members** have no marker for their current death, so the scan is not restricted for them:
  they fight on (3.4).
- **Status:** activity "Waiting out the realm point timer", set once; the countdown ("worth realm points in N s;
  leaving in M s") in the progress text, which `SetStatus` saves at most every 12-16 s (WBC:4675-4694). No forced save
  (`SetRvrStatus` forces one on every call, WBC:2357). Not one of the watchdog-exempt strings
  (`AutonomousStuckWatchdog.cs:404-411`). Warbands keep "Formed up at rendezvous".
- **At wait start by hooks 1-2 (once):** stop moving; free a siege job (3.3); reset the route state
  (`ResetRouteOrderState`, WBC:4644-4660, and `_keepStallSince = 0`, `AutonomousWorldBotController.KeepTravel.cs:19`),
  so the first route after the wait doesn't count the wait as a stall. The same reset when hooks 1-2 end a wait. The
  warband gate does none of this; the regroup manages its members.

## 5. Never waits

| Who | How the code tells | Effect |
|---|---|---|
| Bots resurrected where they fell (they fight on) | only a release sets `IsReturningAfterRelease` (GB:1098); a resurrection clears it with no release (GB:1121-1139, :1126) | no marker for that death |
| Warband members resurrected in the field | no marker for that death, as above | walk back with the warband but don't hold it (3.4, choice 18) |
| Relic carriers | `GameRelic.IsPlayerCarryingRelic(bot)` (`keeps/Relics/GameRelic.cs:460`; WBC:459-460, :1723) | RvR hook and warband gate skip |
| Relic escorts, interceptors and pickers | destination id starts with `rvr-relic-carrier-` (WBC:1793; EL:1327); any realm's carried or dropped relic is a target (WBC:2202-2226) | RvR hook skips |
| Relic-event forces | in a battle with no keep plan (EL:766, :769-778): the attackers, defenders and third realm of the keep battle the relic left (EL:1305-1310), and forces that join it (EL:1166-1176) | RvR hook skips |
| The owner's companions; gamebots in a player's group | Tick returns first (WBC:226-227), the threat scan too (FT:133); `/spawn` helpers never get the timer (ARPR:21-22); a player's invite ends a wait (3.8) | every hook runs after |
| Bots in a muster | rally and muster orders return first (WBC:1712-1717): every force of an event whose battle has not started, and defenders of a player-triggered defence while they muster (EL:725-752). A warband in a muster regroups after a casualty instead (WBC:479-484); the gate says go for a committed session and writes nothing (3.4) | before the RvR hook; a waiting bot called to one stops waiting (3.5) |
| Warbands outside a siege battle, as single bots | Tick sends them to the regroup (WBC:482-484); the RvR hook doesn't start a wait for `dynamicWarband && !battleActive` | the warband gate instead (3.4); drafted mid-wait, 3.3 at the slot |
| Group PvE parties | the gate says go for any session that is not RvR (3.4) | never wait |
| Bots in another region than their fight (invaders, attackers of enemy-frontier keeps) | released to their capital (GB:1084-1089) | no wait |
| Over-cap battleground bots | their tour ends before the hook (BG:37-42) | never reach it |
| Every bot after a server restart | the timer is memory only (ARPR:90; GB:938), and so is the marker | nothing to wait for |
| Bots on PvE goals | hook 3 writes no marker for them (it checks the goal, 3.5). Hooks 5 and 6 run for every goal (GC:1438-1439; FT:119-121) but find no marker. Hooks 1-2 run only in the battleground tour and RvR turns. Hook 4 says go for Group PvE | never wait |

## 6. The switch

- **Property:** `bot_rp_timer_wait`, category `server`, a `public static bool BOT_RP_TIMER_WAIT` in
  `RpTimerWaitScript` (`[ServerProperty]` fields are found only when public and static,
  `ServerProperties.cs:2577-2588`). Code default `false`, like `si_start_choice`
  (`scripts/hearthdaoc/SiStartChoiceScript.cs:19-22`). Description: "Released gamebots wait at a safe spot until their
  trip back to the fight ends as their rp_worth_seconds timer does, so they come back worth realm points".
- **HearthDAoC turns it on:** `HEARTHDAOC_BOT_RP_TIMER_WAIT` (`on` or `off`, case ignored, default `on`) goes `.env` →
  `deploy/compose.yml` → `deploy/entrypoint.sh` → `deploy/bin/server_properties.py` (a new required
  `--bot-rp-timer-wait`, declared after `--si-start-choice` at server_properties.py:84) → the property, at every start,
  exactly as `HEARTHDAOC_SI_START_CHOICE` does (compose.yml:24, entrypoint.sh:28-30, server_properties.py:25-31 and
  :94-95, `.env.example`:18-21). It prints "Bot realm point timer wait: on" or "off" when it changes the row. `./hdc
  update` adds the new line to an existing `.env` (`deploy/tests/test_si_start_choice.py:3-5`).
- **Off with one line:** `HEARTHDAOC_BOT_RP_TIMER_WAIT=off` in `~/hearthdaoc/.env`, then `./hdc up`.
- **Read live** on every turn, so it can also be switched with `&serverproperties refresh` after editing the row.
- **What off does** (the only description; 3.4, 3.5, 7.1, 7.2 and 10 follow it):
  - Hook 3 writes no marker. On a waiting bot's next controller turn it ends the wait: latched Left, `leave
    reason=off` (3.5).
  - `IsWaiting` answers no, so hooks 5 and 6 act as upstream.
  - The warband gate says go at once and writes nothing: no marker change, no log line. So a held member's wait is
    ended by its own hook 3 (`off`), never by the gate (`due`). A Released marker stays as it is, as hook 3 leaves it.
  - Hooks 1-2 return false at once. Hook 3 runs before them on the same turn, so no wait is left for them.
  - The `Dying` handler still writes death records and the `died` line, so on and off can be compared, and still ends
    a wait at a death (`leave reason=died`, 3.7).
  - The `MemberJoined` handler still ends a wait when a player invites the bot (`player-group`, 3.8): after the invite
    hook 3 never runs for it (WBC:226-227).
  - So the log has only `died` lines, plus one `leave` for each wait running at the switch: `off`, or `died` or
    `player-group` if the bot is killed or invited into a player's group before its next turn.
- **Also off when `rp_worth_seconds` is 0:** time left is then always 0 (2.1). HearthDAoC doesn't set it
  (`server_properties.py:92-95` writes only `command_plvl_overrides` and `si_start_choice`).

## 7. Code

### 7.1 `scripts/hearthdaoc/RpTimerWait.cs`: the decisions

`namespace DOL.GS.HearthDAoC; public static class RpTimerWait`. Plain values in and out; no server state.

| Member | In | Out |
|---|---|---|
| `WorthlessForMilliseconds` | last death tick, now, `rp_worth_seconds` | ms until worth (0 = worth), as ARPR:82-86 |
| `BestSpeed` | live `MaxSpeed`, `MaxSpeedBase`, best own speed value (%) | units/s |
| `TripMilliseconds` | distance, units/s | ms, rounded down; `long.MaxValue` with no speed |
| `FirstContactPoint` | arrival, central keep, 0.6, 900, 5,000 | a 2D point |
| `LeaveTick` | last death tick, `rp_worth_seconds`, trip | game tick: the moment time left = trip (2.3); the controller's think wake (2.3, 7.3) and the `leaveIn` log field (10.5) read it, Decide does not (it compares time left with trip) |
| `Note` (hook 3) | switch, marker, death count, alive, returning, goal, region, position, assignment id, in a group, force committed, muster order | the new marker and its log action (Released; Left with `off`, `changed` or `called`), or the old one |
| `Decide` (hooks 1-2) | marker and current death count, the hook's case, region, assignment id, stored and current event keep id, exclusion, target known and its region, inside the first-look gate (bind 750, arrival 2,500, slot 200), time left, trip, now (the `started` of the marker that Start or Convert writes) | `Ignore`, `Skip(reason)`, `Start`, `Convert` (warband to siege, 3.4), `Hold`, `Leave(reason)`; its reasons include `called` (a siege marker whose stored keep is not the current one, 3.3) |
| `WarbandWaits` | switch, objective kind, force committed, each member's marker, death count and time left, march, relic carrier | wait or not: wait while the largest time left among members released for this death > march; go with the switch off, a non-RvR kind or a committed force, and then `WarbandMarks` is not called (3.4, section 6) |
| `WarbandMarks` | gate result, the rendezvous region, and for each member its marker, death count, time left, region, slot, assignment id; session id; now (a Waiting marker's `started`) | each member's new marker and its log action (`start`, `leave`, `skip`, or none): Released to Waiting only in the rendezvous region while holding; Released or Waiting to Left when opening; a Left marker never changes |
| `Died` (3.7) | marker, death count now | Left with `died` for a Waiting marker of an older death count; Left with no line for a Released one; otherwise the old marker |
| `JoinedGroup` (3.8) | marker, death count, leader is a player | Left with `player-group`, or the old marker |
| `IsWaiting` | switch, marker, death count, time left, region, assignment id, player-led, in a group, in a battleground region and distance to its `BotArrival`, distance to the release point | the "counts as waiting" rule of 2.4 |

Types: `RpWaitPhase` (Released, Waiting, Left); `RpWaitCase` (Battleground, Frontier, Siege, Warband); `RpWaitMarker`,
immutable (death count, phase, case, release region, release point, region, spot, assignment id, session id, event
keep id, started); `RpWaitSlot`, the per-bot holder of the current marker, with `TrySwap(expected, next)` by
`Interlocked.CompareExchange` and `Apply(decide)`, the handlers' retry loop (7.2); `RpDeathRecord` (death count,
region, position, tick, timer value). Constants: first-look gates 750 (bind), 2,500 (battleground)
and 200 (warband slot, 3.4); walk back beyond 200; contact point 0.6, 900 and 5,000; frontier regions 1, 100 and 200.

### 7.2 `scripts/hearthdaoc/RpTimerWaitScript.cs`: the game wiring

`namespace DOL.GS.HearthDAoC; public static class RpTimerWaitScript`.

- The switch (section 6).
- `WorthlessFor(GameBot)`: reads the timer key, `Properties.RP_WORTH_SECONDS` and `GameLoop.GameLoopTime`.
- `BestSpeed(GameBot)`; `NoteRelease(GameBot)` (3.5); `IsWaiting(GameBot)` (2.4, 3.6, section 4); `WarbandWaits(...)`
  (3.4: with the switch off (section 6), a non-RvR session or a committed force, go at once and no writes; otherwise
  decides, then writes the members' markers through `WarbandMarks`).
- The `Dying` handler (3.7: the death record, then `Died`) and the `MemberJoined` handler (3.8: `JoinedGroup`),
  registered at script load, and the `HEARTHDAOC_RP_WAIT` log (10.5).
- Every entry point reads the marker first and returns at once for a bot with none (one dictionary read);
  `NoteRelease` also reads the release flag. Then the switch (section 6). Nothing calls `IsSafeArea`, an allocation hot
  spot (FT:142-143). Event-layer calls happen only in `NoteRelease`, only for a waiting bot (3.5), and in
  `WarbandWaits`, one `IsForceCommitted` read per pass of an RvR session (3.4).
- **Marker writes and threads.** Bot brains tick in parallel (`Managers/GameLoop/GameLoop.cs:80-83`;
  `ECS-Services/NpcService.cs:46`). The gate writes other members' markers from one member's thread, under the
  coordinator lock (GC:212). Hooks 1-3 and the handlers (3.7, 3.8) write markers on other threads, outside that lock.
  So:
  - The TempProperty holds one `RpWaitSlot` per bot, created by hook 3 at the bot's first release; the other writers
    touch only a bot that has one.
  - Every marker write swaps a new immutable `RpWaitMarker` into the slot with `Interlocked.CompareExchange`, against
    the marker the writer read (compare-and-set).
  - A writer that loses the swap writes nothing and logs nothing. A hook or the gate decides again from the new value
    on its next turn or pass. A handler (3.7, 3.8) has no next turn, so it reads again and retries (`Apply`) until
    its swap succeeds or nothing is left to write.
  - The `start`, `leave` and `skip` lines are logged only after a successful swap, so each change logs once.
  - The gate only changes Released to Waiting while it holds, and Waiting or Released to Left when it opens. It never
    writes over a Left marker.
  - No lock is taken for the swap. Hook 3's event-layer calls come before it.

### 7.3 `scripts/hearthdaoc/RpTimerWaitController.cs`: the controller side

`namespace DOL.GS; public sealed partial class AutonomousWorldBotController` (the class is partial, WBC:22; BG is
another part). It holds `RpTimerWaitBattleground` and `RpTimerWaitRvr` (the two hook calls) and their shared wait:
gather the inputs, call `RpTimerWait.Decide`, then act (move, status, siege job, route reset, think wake,
`_nextRvrPlanReview`). It uses only these private members: `IssuePath` (WBC:4128), `SetStatus` (WBC:4662),
`SetBattlegroundStatus` (BG:248), `GoalText` (WBC:4698), `ResetRouteOrderState` (WBC:4644), `ReleaseSiegeJob`
(Siege.cs:465), `_siegeJobKeep`, `_keepStallSince` (KeepTravel.cs:19), `_rvrDestination` (WBC:113) and
`_nextRvrPlanReview` (WBC:2328). An upstream rename breaks the build, the loud failure wanted; the source check (10.2)
names them too.

### 7.4 The six upstream lines

| # | File | Where | Call |
|---|---|---|---|
| 1 | BG | after 68 | `RpTimerWaitBattleground(brain, bot, bracket, central)` |
| 2 | WBC | after 1736 | `RpTimerWaitRvr(brain, bot, battleActive, dynamicWarband, committedPlan != null)` |
| 3 | WBC | after 319 | `HearthDAoC.RpTimerWaitScript.NoteRelease(bot)` |
| 4 | GC | in 1986-1987 | `!HearthDAoC.RpTimerWaitScript.WarbandWaits(...)` |
| 5 | GC | after 1480 | `!HearthDAoC.RpTimerWaitScript.IsWaiting(bot)` |
| 6 | FT | after 157 | `.Where(target => !HearthDAoC.RpTimerWaitScript.IsWaiting(bot) \|\| FiringOnRealm(bot, target))` |

Each has a `// HearthDAoC:` comment line above it. Nothing else upstream changes. No seventh hook: the player-group
latch (3.8) and the death record (3.7) are event handlers, and the "called away" check rides on hook 3.

### 7.5 What the unit tests reach

- Without a server: all of `RpTimerWait`, with `RpWaitSlot`'s swap; `RpTimerWaitScript.WorthlessFor` on a gamebot
  built without its constructor (the pattern of `Tests/UnitTests/UT_AutonomousBotRealmPointRewards.cs:51-66`); the
  switch's declaration.
- Not: the controller part (it needs a controller, a world and the navmesh), the hook lines (source checks, 10.2), the
  event handlers' wiring (they need a real death or group; their decisions, `Died` and `JoinedGroup`, are tested), the
  event-layer reads in `NoteRelease` and `WarbandWaits`, and the threat scan (in game, 10.4).

## 8. Hazards from the code checks

The table is in Appendix A, at the end.

## 9. Choices this spec makes (owner may change)

1. **Name and default** (owner, 2026-10-13: approved)**:** `bot_rp_timer_wait` and `HEARTHDAOC_BOT_RP_TIMER_WAIT`,
   category `server`, off in code, on in HearthDAoC (the `si_start_choice` pattern).
2. **Battleground waves: deferred** (owner, 2026-10-13). The owner chose a sliding wave ("which ever is more likely to
   have bots go in a group"), then chose to stage the work. In this stage each battleground bot leaves at its own
   moment. Waves come in a later stage: the owner named the commander phase (roadmap part 7); the RvR groups (part 4)
   would also fit. Appendix B keeps the design so far and what its two reviews found.
3. **Best speed:** the largest of live speed, base speed, and base speed times its own best speed song (2.2).
4. **First contact point:** `0.6 × |AC| − 900 − 5,000` from the arrival toward the central keep, from the roam anchors
   and the scan radius (3.1).
5. **Trip targets:** battleground, the first contact point; frontier solo, its destination, else its death spot;
   siege, the event keep; warband, the death spot of the released member with the most time left, from the
   rendezvous, at the fastest member's best speed.
6. **Porter wait for frontier invaders:** not modelled. A bot in another region than its fight never waits. Its trip
   (7 min or more, README 3.3) outlasts the timer anyway, and an unknown route can never turn into a long wait in a
   capital.
7. **Spots:** battleground slots 1-12 around `BotArrival`; frontier and siege, the release point; warband, its slot,
   also after a draft into a battle (3.4). A bot more than 200 from its spot walks back, from any distance.
8. **First-look gates:** within 750 of the release point; within 2,500 of `BotArrival`; a drafted warband member
   within 200 of its slot. Outside them, no wait (latched).
9. **Leave timing:** the next think is set to the leave moment plus half a game tick (at least 250 ms); a woken
   think that something else takes leaves at the next hook turn (2.3).
10. **Frontier re-pick:** held until the bot is worth points again.
11. **Fighting back:** it answers enemies attacking it or a realm-mate within 1,000; it charges nothing it only sees.
    At a bind (frontier solo, siege), only its own attackers and, in a siege party, its group mates' (the scan is off
    in bind areas, FT:138).
12. **Task or goal ends while waiting:** the wait ends (2.4). A new assignment or region ends it on the next
    controller turn (hook 3, `changed`). A battleground bot whose tour ends is already at its exit (BG:202-229). A
    warband that disbands mid-wait ends its wait too; its members may go out worth nothing (3.4; section 13).
13. **Dies again while waiting:** the wait ends at the death (`leave reason=died`, logged by the `Dying` handler,
    3.7). Released again: a new wait on the new timer. In a warband the gate waits for the new timer, and the casualty
    restarts the settle too (GRS:25). Resurrected instead of released: the old wait ends, it fights on.
14. **Switched off mid-wait:** the next controller turn ends it (`leave`, `reason=off`; section 6).
15. **Siege job:** freed at wait start (3.3).
16. **Logging:** the four `HEARTHDAOC_RP_WAIT` actions (10.5); `died` also with the switch off; one `leave` for every
    `start`.
17. **Warband status:** unchanged ("Formed up at rendezvous"): no new watchdog exemption, no extra hook.
18. **Resurrected warband members' timers** (owner, 2026-10-13: "yes don't hold the warband back")**:** not counted.
    Only members released for their current death hold the gate; a resurrected member gets no wait and fights on, as "A,
    fights on" says. It still walks back with the warband and stands at its slot until the warband leaves (the existing
    regroup, GRS:17-19, :45-56). Alternative: count their timers too. A warband whose only casualty was resurrected in
    the field would then wait at its border keep until that member can make the march, up to about 4-5 minutes after the
    walk back (est.).
19. **Never waits, beyond the design's relic carriers and escorts** (section 5):
    - relic interceptors and bots heading for a dropped relic (their target moves);
    - every force of a relic carrier event: attackers, defenders and third realm;
    - a warband with a relic carrier in it;
    - bots released in another region than their fight: invaders, attackers of enemy-frontier keeps;
    - bots in a muster when they release (the muster holds them already), and a warband enrolled in an event whose
      battle has not started (the gate says go, 3.4);
    - gamebots in a player's group.
    Each could wait instead; each needs its own trip rule.
20. **Called away ends the wait:** a frontier solo whose force joins an event (a muster, a battle draft, a relic event),
    or a siege or warband member called to a muster, stops waiting and goes; a player's invite ends it too. A held
    warband drafted into a battle with no muster keeps waiting, at its slots (3.4). Alternative: let a drafted frontier
    solo wait on at its bind as a siege member (3.3). A waiting siege member whose force the draft moves to another
    defence stops waiting too (`called`, hook 2 sees another keep, 3.3); a drafted warband member at its slot likewise.
    Alternative: wait on at its spot (its bind, or a drafted warband member's slot), measured to the new keep. A bot
    called to a muster can't wait on: it would be missing from the muster, which marches on attendance (EL:706, :714).

## 10. Testing

### 10.1 C# unit tests (CI)

`Tests/UnitTests/UT_RpTimerWait.cs` and `Tests/UnitTests/UT_RpTimerWaitScript.cs`, namespace `DOL.GS.Tests`, each a
`public sealed class` in a file of its own name, with a `// HearthDAoC:` header (as `UT_ClassicBattlegrounds.cs:1-15`).
One row per rule:

- **Time left:** none on record (-1) gives 0; `rp_worth_seconds` 0 or below gives 0; just died gives 300,000;
  299,999 ms later gives 1; 300,000 later gives 0 (the `>=` of ARPR:86); a clock before the death tick gives 300,000.
- **Best speed:** hurt below base gives 191; its own song of 140 gives 267.4; a faster live speed (another's song)
  wins.
- **Trip:** 8,181 at 191 gives 42,832 ms; no speed means it never waits.
- **First contact:** the three arrival points and the central keep give 2,147, 8,181 and 8,133 from the arrival (±1);
  a short field gives the arrival itself.
- **Leave tick:** `LeaveTick` is the last death tick + `rp_worth_seconds` × 1000 − the trip; at that tick time left
  equals the trip.
- **Note (hook 3):**
  - alive, returning, goal RvR or Battleground: Released for this death, with region, point and assignment id;
  - a PvE goal: no marker;
  - not returning (resurrected) or dead: marker unchanged;
  - already Released or Left for this death: unchanged;
  - a marker of an older death (already Left by the `Dying` handler, 3.7), then a release: Released for this death,
    no log line;
  - switch off with a release: no marker;
  - switch off with Waiting for this death: Left, `leave reason=off`; with Released: unchanged;
  - Waiting with another assignment id, or in another region: Left, `changed`;
  - Waiting warband with no group: Left, `changed`;
  - Waiting frontier with its force committed: Left, `called`;
  - Waiting siege with a muster order: Left, `called`; Waiting siege committed with no muster order: unchanged (a
    move to another keep is Decide's, below);
  - Waiting warband whose session has a muster order: Left, `called`; with none: unchanged;
  - Waiting with nothing changed: unchanged.
- **Died (3.7):**
  - Waiting for the previous death count (killed while waiting): Left, `leave reason=died`, with the switch on or off;
  - Released for the previous death count: Left, no line; so a gate swap to Waiting that read it before the death
    fails, with no `start`;
  - Left: unchanged;
  - then resurrected (no release): Note, Decide, `IsWaiting` and the gate ignore it, and no second `leave` comes;
    then released instead: Note writes Released for the new death.
- **Decide (hooks 1-2):**
  - no marker, or a marker for an older death: Ignore;
  - Left: Ignore after any later change of speed or destination (the latch);
  - Released first look: each exclusion gives Skip with its reason; the bot in another region than its release point
    or its target (hook 2), Skip(other-region); no target, Skip(no-target); outside the first-look gate,
    Skip(moved-away); time left ≤ trip, Skip(trip); otherwise Start (a siege stores the event keep id);
  - Released with the warband-outside-battle case: Ignore (the gate decides);
  - Waiting, same case: Hold at time left = trip + 1 ms; Leave(due) at time left = trip, a battleground bot too;
  - Waiting more than 200 from its spot: Hold with a walk back; 3,000 from it after a fight: still Hold;
  - Waiting with another assignment id or region: Leave(changed);
  - Waiting frontier, the hook sees a siege, or Waiting siege, the hook sees frontier: Leave(changed) (hook 3 has
    usually ended a drafted solo's wait first, as `called`); Waiting, the hook sees a warband outside battle:
    Leave(changed); a relic event: Leave(relic);
  - Waiting with a relic exclusion: Leave(relic); target gone: Leave(no-target);
  - Waiting siege, the hook sees a siege at another keep: Leave(called), in its region or another (the keep check
    comes before the region check); a Converted warband member likewise; the same keep: Hold;
  - Waiting warband, the hook sees a siege, within 200 of its slot in the stored region: Convert, storing the event
    keep id; 300 from it: Leave(moved-away); within 200 but time left ≤ trip to the keep: Leave(due);
  - Released warband member in a battle, 3,000 from its bind: Skip(moved-away);
  - a new death and release: Start again.
- **Warband gate:**
  - waits while the largest time left among released members > the march; equal means go;
  - a resurrected member (no marker for this death) with time left above the march doesn't hold it;
  - a relic carrier means go; a Group PvE session means go, even with a member's time left above the march, and
    writes nothing; all worth means go;
  - the switch off means go and writes nothing, even with a member Waiting or Released for this death above the
    march: a Waiting member stays Waiting until its hook 3 (`off`), a Released one stays Released;
  - a committed force (`IsForceCommitted`) means go and writes nothing, even with a member's time left above the
    march; a member already Waiting is left to hook 3 (`called`);
  - a member killed again and released makes it wait again;
  - while holding: each member Released for this death in the rendezvous region becomes Waiting, case warband, spot =
    its slot, with the session id, and logs `start` at that swap; a Waiting one is not written again and logs nothing
    on later passes; a member Released in another region stays Released, still holds it, and turns Waiting on the
    first pass after it enters the region; a resurrected member gets no marker; a member Left for this death stays
    Left;
  - opening (switch on): each Waiting member for this death becomes Left with `leave reason=due`; a Released one
    still worth nothing becomes Left with `skip reason=trip`; a marker hook 3 has already latched Left (`called`) gets
    no second `leave reason=due`; an older death's marker (Left, 3.7) is not touched;
  - a marker that turns Left between the gate's read and its write stays Left: the gate's swap fails and logs
    nothing.
- **Marker swap** (`RpWaitSlot`, plain values): a swap against the marker read succeeds; a second swap from the same,
  now out-of-date, read fails and changes nothing; `Apply` (the handlers' retry) reads again after a lost swap and
  stops once its decision leaves the marker as it is. The gate and handler races above are tested on it.
- **Player group (3.8):** Released or Waiting for this death, joining a group led by a player: Left (Waiting logs
  `player-group`); joining a group led by a bot: unchanged; an older death's marker: unchanged.
- **Is waiting:**
  - Waiting for this death, time left > 0, same region and assignment id, not player-led: true, however long since a
    hook last ran (60 s, 5 min);
  - false with the switch off, for another death, with time left 0, in another region, with another assignment id,
    when player-led, or when Left;
  - Waiting warband with no group: false;
  - Released in a battleground region within 2,500 of its `BotArrival`: true; at 2,600: false;
  - Released in its frontier release region within 750 of its release point: true; at 800: false;
  - Released in its capital at its bind (an invader): false; an invader's Released marker in the frontier: false;
  - Released with time left 0, for an older death, or with another assignment id: false.
- **Wiring** (`UT_RpTimerWaitScript`): `WorthlessFor` reads the literal key
  `"autonomous.rvr.last.realm.point.death.tick"` (the test project can't see the `internal` const; `source/server` has
  no `InternalsVisibleTo`). `Properties.RP_WORTH_SECONDS` is saved, set and restored: it is 0 in tests, because the
  field has no initializer (`ServerProperties.cs:852`). `GameLoop.GameLoopTime` is set by reflection
  (`UT_BonedancerSupportCastLifecycle.cs:387-388`). The switch is a public static field declared
  `[ServerProperty("server", "bot_rp_timer_wait", …, false)]`.
- **CI:** add `|FullyQualifiedName~UT_RpTimerWait|FullyQualifiedName~UT_RpTimerWaitScript` to the filter at
  `.github/workflows/server-image.yml:116`, and the same two names to `SERVER_UNIT_TESTS` and to the expected list in
  `deploy/tests/test_workflows.py:236-245` and :261-273 (which also checks each file holds `public sealed class
  UT_X`). CI runs no fork test missing from that filter.

### 10.2 Source checks (Python, `deploy/tests/test_rp_timer_wait.py`)

- Each of the six lines once, with its `// HearthDAoC:` comment, in its method and in order (index comparisons, as
  `deploy/tests/test_battlegrounds.py:120-130` does):
  - BG, in `ExecuteBattleground`: after `BotOverCap(` and `bot.CurrentRegionID != bracket.RegionId`, before
    `TryRunSiegeJob(bot)`.
  - WBC, in `ExecuteRvr`: `RpTimerWaitRvr(` after `HandleSiegeRally(` and the stale-target block's
    `_nextRvrPlanReview = 0;`, before `if (TryRunSiegeJob(bot)) return true;` and `FindRvrTarget(bot)`.
  - WBC, in `Tick`: `NoteRelease(bot)` after `ObserveDeaths(bot);` and the companion return; `if
    (!bot.IsPlayerLedGroup)` still directly followed by `bot.HandOverReleaseReturnToGroup();`.
  - GC: `WarbandWaits(` in the same condition as `session.Recovery.TryComplete(`, before it.
  - GC: `IsWaiting(bot)` inside the `available` filter of `TryFormGroups`.
  - FT: the `IsWaiting(bot) || FiringOnRealm(bot, target)` filter inside the `nearby` chain, before `.OrderBy(`.
- `RpTimerWait` appears in no other upstream file; counts: BG 1, WBC 2, GC 2, FT 1.
- `RpTimerWaitScript.cs` registers handlers for `GameLivingEvent.Dying` and `GroupEvent.MemberJoined`.
- The upstream facts the fork mirrors, so a change upstream fails here: ARPR's `long worthInterval =
  Math.Max(0, Properties.RP_WORTH_SECONDS) * 1000L;`, `bool isWorthRealmPoints = previousDeath < 0 || now -
  previousDeath >= worthInterval;` and the key string; BG's roam anchor `0.6f` and `GetRandomPoint(zone, anchor,
  900,`; WBC's `TargetSearchRadius = 5000`; the `"RvrEventForce"` key; `public static Vector3
  RendezvousFormationPoint(`; and the private members the controller part uses (7.3).
- `deploy/tests/test_battlegrounds.py:160-192` passes unchanged.

### 10.3 Deploy tests (the switch)

In the same file, copying `deploy/tests/test_si_start_choice.py:35-106`:

- The entrypoint passes `--bot-rp-timer-wait "${HEARTHDAOC_BOT_RP_TIMER_WAIT-on}"`. With nothing set it writes
  `True`; `OFF` in any case writes `False`; a bad value stops the start (exit 2, "HEARTHDAOC_BOT_RP_TIMER_WAIT must be
  on or off, got …") and writes nothing.
- `compose.yml` passes it with default on; `.env.example` has `HEARTHDAOC_BOT_RP_TIMER_WAIT=on` under a comment that
  says what `off` does; `HANDOFF.md` lists it.
- The C# declaration's description equals `server_properties.py`'s; category `server`; default `false`.
- Existing tests that change:
  - every CLI call in `deploy/tests/test_server_properties.py:102-141` gains the new required argument, except the
    one at :129, which tests a missing argument;
  - the expected stdout at `test_server_properties.py:110` and :141 gains "Bot realm point timer wait: on" (both run
    on a database with no `bot_rp_timer_wait` row);
  - the expected output at `deploy/tests/test_si_start_choice.py:60-61` gains the same line.
  - Unchanged: `test_server_properties.py:113`, :119, :123 and :131 (`assertIn` still finds `--si-start-choice` first
    in the list of missing arguments, because `--bot-rp-timer-wait` is declared after it; argparse lists missing
    required arguments in the order they were declared), and `test_si_start_choice.py:67` and :75.

### 10.4 In game (owner, after merge)

1. After `./hdc update`: `.env` has `HEARTHDAOC_BOT_RP_TIMER_WAIT=on`, and the start prints "Bot realm point timer
   wait: on".
2. **Battleground.** With a character of a battleground's levels, kill an enemy bot near the central keep. The log
   shows its `died … worth=yes`, then about 30 s later `start case=battleground` with `trip=11` (Albion) or about 43
   (Midgard, Hibernia).
3. Go to that realm's arrival point outside its portal keep (Albion 36428,51260; Midgard 53150,26093; Hibernia
   19714,19085; the same in all four). Its bots stand there, apart, and don't run at you, even one just arriving
   through the teleporter. Hit one: it, and its realm-mates within 1,000, fight back, then walk back to their spots.
4. At its `leave` it walks out on its own (no waves in this stage). Kill it in the field: realm points are paid, with no
   "has been killed recently and is worth no realm points!" message; the log shows `died … worth=yes`.
5. Kill one while it waits: the "worth no realm points" message, as expected, `died … worth=no` and, at the same
   death, `leave reason=died`; after its next release, a new `start`. A warband member resurrected at its slot
   instead gets no new `start`.
6. Invite a waiting bot into your group: `leave reason=player-group`. Remove it before its timer runs out: it doesn't
   walk back to its spot.
7. **Frontier**, over a day of play: `start case=frontier` and `case=siege` for defenders near their home binds
   (Fensalir Faste, Mjollner Faste, Dun Ailinne …); `skip reason=other-region` for invaders; `case=warband` with a
   `group=`, one `start` per released member at the slots and one `leave` each when the warband sets out.
8. At a home bind, hit one waiting bot: it fights back; solo neighbours do not (expected: the scan is off at a bind,
   FT:138).
9. **Off:** `HEARTHDAOC_BOT_RP_TIMER_WAIT=off`, `./hdc up`: "Bot realm point timer wait: off"; no `start` lines;
   `died` lines still come; bots run straight back as before.

### 10.5 Measuring it in the server log

One line per event, all `HEARTHDAOC_RP_WAIT action=…`, in `/data/logs/server.log` (read with `docker exec
hearthdaoc-server grep … /data/logs/server.log`; `./hdc logs` keeps only 200 lines):

| action | When | Fields |
|---|---|---|
| `died` | every gamebot death with an enemy-realm killer (the `RVR_BOT_KILLED` filter, ARPR:66-68), switch on or off | bot, id, realm, goal, killerRealm, `worth=yes` or `no`, `sinceLastDeath`, region, position |
| `start` | a wait starts | case, region, `worthIn`, `trip`, `leaveIn`, spot; warbands: one line per member, written by the gate, with `group`; a drafted member's new siege wait keeps its `group` |
| `skip` | a released bot still worth nothing doesn't wait, at its first look or at the warband gate's opening | case, `worthIn`, reason: `trip` (no need, it arrives worth), `other-region`, `moved-away`, `relic`, `no-target` |
| `leave` | a wait ends; `died` at any death of a waiting bot, a monster kill included (3.7) | case, `waited`, `worthIn`, `trip`, reason: `due`, `off`, `changed`, `called`, `player-group`, `battle`, `moved-away`, `relic`, `no-target`, `other-region`, `died` |

Every `start` has exactly one `leave`, except across a server restart: a line is written only after a successful
marker swap (7.2), and a death ends a running wait at once (3.7). `worth` is the timer as ARPR:86 read it for
that death: the death record (3.7) keeps the timer value from the previous death.

What to read:

- **Kills that paid nothing:** the share of `worth=no` among `died`, in total and per region (250-253 the
  battlegrounds; 1, 100 and 200 the frontier). Compare a few hours with the switch on and off.
- **Before this release:** the same share from `RVR_BOT_KILLED` (ARPR:70-73): a bot `id=` killed again within 300 s of
  its previous line paid nothing. A lower bound: deaths to monsters and neutral guards restart the timer but are not in
  that line.
- **The cost:** `waited=` on `leave` (battlegrounds about 230-260 s, est.: Albion about 259 s, Midgard and Hibernia
  about 227 s, 2.5); `start` lines minus `leave` lines up to a moment is how many bots sit out then.
- **What remains:** `worth=no` from bots killed again at their spot (players camping an arrival point), resurrected
  bots, waits ended early (`leave` reasons other than `due`), and the `skip` reasons.

## 11. Documentation

- `docs/fork/FORK.md`: a row in the server-code table (the three new files, the six marked lines, the tests).
- `deploy/HANDOFF.md` (settings, :87-91) and `deploy/.env.example`: the new setting.
- `docs/fork/verification/`: the checks of 10.4 with the owner's results.

## 12. Out of scope

- The later roadmap parts (section 1): base class and promotion at 5; battleground regulars and recycling (#110);
  RvR groups and keep choice; epic armour; ordinary quests; the realm commander; the optional AI bundle, chat and war
  council.
- Battleground waves: deferred to a later stage, with the realm commander or the RvR groups (choice 2, Appendix B). In
  this stage each battleground bot leaves at its own moment (2.3, 3.1).
- Changing the timer or its value; `lord_rp_worth_seconds`, which counts from the lord's last spawn
  (`keeps/Gameobjects/Guards/Lord.cs:54-59`).
- The longer corpse wait (README 4.1, variant 1).
- Research side findings, unchanged: gamebots are paid for a player kill inside that player's own 300 s
  (`AbstractServerRules.cs:1916` runs before :2034); an over-cap battleground bot's first death ends its tour
  (BG:37-42); invading warbands have no route home to regroup (frontier check, missed[5]); movement-first pet classes
  don't rebuff out of combat.
- Upstream: a candidate later, only with the owner's go-ahead (upstream contributions are paused).

## 13. Risks

- **Thinner fights:** a dead battleground bot is back at the first contact point about 5 minutes after its death
  and at the central keep about 6-6.5 minutes after, instead of about 2. If the battlegrounds feel empty, raise their
  share with `./hdc bot-goals set` (`deploy/HANDOFF.md:95-110`).
- **Camped arrival points:** players camping an arrival point can keep killing waiting bots (worth nothing), and each
  death restarts that bot's wait. They fight back; guard cover at the spot is unverified (they stand 1,400-1,700 from
  the portal keeps' guards).
- **No realm-mate defence at a bind:** a player can kill bots waiting at a home bind one at a time while their solo
  neighbours stand still (section 4; FT:138). Each death restarts that bot's wait. Today bots don't stand at binds.
- **The neutral start:** deaths to the central keep's neutral guards and to monsters restart the timer (ARPR:88-90), so
  they cause waits too and slow the first capture of a neutral keep.
- **Early arrivals:** horse routes (WBC:1895) and another bot's speed song beat the estimate; a warband leader may pick
  a nearer target than its death spot. Each makes a bot arrive early, by at most the difference in trip.
- **Waits that end early:** a warband task that expires mid-wait, a muster call, a draft to another keep or a player's
  invite sends a bot out still worth nothing. Rare for warbands: a task lasts 45-120 min
  (`AutonomousGroupTaskClock.cs:18`), a wait about 5. The `leave` reasons count them (10.5).
- **Goal clocks:** battleground tours and warband tasks keep running during waits; a battleground bot that dies often
  without fighting nears the 45-minute goal watchdog (`AutonomousStuckWatchdog.cs:38`, :368-374).
- **One by one:** until waves come (Appendix B), battleground bots go back alone as each becomes worth points, and
  a lone bot can meet an enemy group.
- **Upstream churn:** six marked lines in four upstream files and a partial of the controller. A sync that moves them
  fails the source checks or the build.

## Appendix A. Hazards from the code checks

Each hazard the research's skeptic checks raised (`wave-code-map.json`, the "check" of each section), and how this
design meets it. Rows marked "spec review" came from the review of this spec (2026-10-13).

| Hazard (source) | Handling |
|---|---|
| A wait can switch back on after leaving: a speed song starts, or a wave's time moves (battlegrounds missed[1]; frontier missed[1]) | latch per death count (2.4); best speed counts the bot's own song (2.2); no waves in this stage (Appendix B) |
| Portal keeps can't be pathed by bots (battlegrounds missed[2]) | spot on the field mesh at `BotArrival` (3.1) |
| The trip to the central keep overstates first contact (battlegrounds missed[0]) | first contact point (3.1) |
| The threat scan charges on sight (battlegrounds missed[3]) | hook 6 (section 4); a Released marker counts before the first look (2.4) |
| Movement-first pet classes don't rebuff (battlegrounds missed[4]) | accepted, stated (section 1) |
| Status writes: a countdown in the activity forces saves; exempt strings (battlegrounds missed[5]; frontier corrections[9]; sieges missed[0]) | section 4, Status |
| Deaths with no realm-point purpose (neutral guards, monsters) also cause waits (battlegrounds missed[6]) | accepted: the players' rule; risk in 13 |
| Guards may not cover the arrival point (battlegrounds missed[7]) | waiting bots fight back; risk in 13 |
| Siege leases outlive the death (battlegrounds hooks[1], missed[9]; sieges hazard 0, missed[6]) | `ReleaseSiegeJob` once, at wait start; back by ExecuteRvr's travel, a fresh job near the keep (3.3) |
| `EstimateTravelMinutes` has no speed floor and returns 9999 into battlegrounds (battlegrounds corrections[2], [8]) | not used |
| Leave lag up to ~7.3 s, ~11.7 s at 1,500 bots or more (battlegrounds corrections[5]; frontier corrections[6], whose 13.5 s applies a 12 s cap that never binds) | next think set to the leave moment plus half a tick; a taken woken think leaves at the next hook turn: up to about 11.7 s later per taken turn, or after a fight ends (2.3) |
| Bots resurrected in the field would be frozen in combat (battlegrounds corrections[6]; sieges hazard 19) | marker only from a release (2.4) |
| CI runs only listed tests; the workflow test pins the list (battlegrounds corrections[10]) | 10.1 |
| Tests can't see the internal key (battlegrounds corrections[9]; sieges corrections[6]) | literal key in the test (10.1) |
| Some spots outside the 400 exit radius (battlegrounds corrections[11]) | slots 1-12; a bot farther out walks to the exit first, harmless |
| 45-minute goal clock covers the battleground goal (battlegrounds hazard 1) | a wait adds at most ~260 s with no outcome; fights mark progress; the wait marks nothing |
| The tour clock runs during a wait (battlegrounds hazard 2) | accepted; a tour that ends mid-wait gives a new assignment, which ends the wait; the bot is already near its exit (BG:202-229) |
| Border keeps are not safe areas (frontier corrections[0]) | solo spot is the bind (3.2) |
| Rest set by the hook is woken every turn (frontier corrections[1]) | no rest call (section 4) |
| The destination is re-picked on departure (frontier corrections[2]) | re-pick held until worth (3.2) |
| Targets near the border make solo waits common (frontier corrections[3]) | the rule handles any destination |
| Level-50 members pick a target during the regroup; the leader re-picks on departure (frontier corrections[4]) | march measured to the death spot; risk in 13 |
| On a wipe the fight point fell back to the leader at its bind (frontier corrections[5]) | each bot's own death spot (3.7) |
| Capitals are safe areas; an unresolved route read as 0 would wait the whole timer there (frontier missed[0]) | another region never waits (3.2) |
| `IsSafeArea` allocates on every turn (frontier missed[2]) | not called; marker and switch first (7.2) |
| Speed drops below 33% health; followers' catch-up (frontier missed[3]) | best speed (2.2) |
| Relic escorts measure to a stale carrier (frontier missed[4]) | no relic chaser waits (section 1, departures; section 5) |
| Invading warbands have no route home to regroup (frontier missed[5]) | existing; their waits are cross-region, so none |
| A warband task that expires mid-wait leaves members at border-keep slots (frontier missed[6]) | accepted: the wait ends with the task; members may go out worth nothing (3.4; risk in 13) |
| 15-minute stuck watchdog (frontier hazard 0) | waits are under ~280 s; the release teleport counts as movement; warbands exempt |
| Recruiting takes waiting bots (frontier hazard 2) | hook 5 (3.6); siege parties excepted (section 4) |
| The coordinator lock (frontier hazard 13) | timer reads, one `IsForceCommitted` read, arithmetic and marker swaps only (3.4) |
| Home-frontier attackers wait, enemy defenders don't (sieges corrections[0]) | the rule (3.3) |
| Speed isn't a constant 191 (sieges corrections[1]) | best speed (2.2) |
| A line between WBC:323 and :324 would split an `if` (sieges corrections[3]) | the note goes after 319 (3.5) |
| The switch must be public static; it is 0 or false in tests (sieges corrections[5]) | section 6; tests set it |
| A waiting healer keeps its group's corpses 90 s (sieges missed[2]) | accepted; stated (section 1) |
| A stale "released" would freeze a later resurrected bot (sieges missed[3]) | death count in the marker (2.4); the `Dying` handler latches it Left (3.7) |
| The first controller turn after a release can come seconds late (sieges missed[4]) | all time from the timer; the marker gives only yes/no and the spot |
| A distance test misreads deaths near a bind (sieges missed[5]) | the release comes from the Tick hook (3.5) |
| Per-turn siege and route work (sieges missed[6]) | only at wait start and leave (section 4) |
| A partial couples to upstream privates (sieges missed[7]) | listed and source-checked (7.3) |
| Siege parties re-form forces and reset controller fields (sieges missed[8], hazard 11) | the marker is on the bot (2.4); a merged member keeps waiting (`SiegeParties.cs:31-35`; section 4) |
| A defender within 3,500 waits almost the whole timer (sieges missed[9]) | the rule (3.3) |
| Route stall on resume (sieges hazard 3) | route reset at start and leave (section 4) |
| A hold must return true or the FSM walks the bot (sieges hazard 5) | both hook calls return true while waiting |
| Repel timer, 10 minutes with no attacker present (sieges hazard 7) | no siege waves; a wait is under ~280 s |
| Drafted held forces fill the realm cap (sieges hazard 8, corrections[2]) | as today for a bot walking back |
| The event ends during a wait (sieges hazard 12) | the solo force is released with a new assignment (WBC:233-237), which ends the wait (2.4) |
| A freshness clock on `IsWaiting` lapses during fights, casts and rebuffs, so waiting bots charge and can be recruited (spec review) | no clock: `IsWaiting` reads only the marker and the bot (2.4) |
| Warband members held by the gate were never marked Waiting (spec review) | the gate marks released members Waiting at their slots (3.4) |
| A battleground bot's first think inside runs the scan before hook 1 (spec review) | a Released marker counts as waiting there (2.4, 3.1) |
| A muster, a draft or a player group takes a waiting bot away, and the hook would walk it back later (spec review) | hook 3 ends the wait (`called`), the group handler too (`player-group`) (3.5, 3.8) |
| A held warband is drafted, or joins a battle (ELD:254-311; WBC:474-480), and GC:1864-1871 skips the gate (spec review) | 3.3 with the slot as spot; members leave one by one (3.4) |
| Group PvE parties reach the warband gate after a wipe (spec review) | the gate says go for any session but RvR (3.4) |
| A waiting siege member whose force the draft moves to another defence kept waiting, though a battle draft ends a wait (spec review) | hook 2 compares the stored event keep; another keep ends the wait (`called`, 3.3; choice 20) |
| With the switch off the gate's opening logged `due`, not `off` (spec review) | with the switch off the gate says go and writes nothing; hook 3 logs `off` (section 6) |
| A waiting bot killed and then resurrected never logged a `leave` (spec review) | the `Dying` handler ends the wait at the death (`died`, 3.7) |
| The gate writes other members' markers from another thread, so updates could be lost (spec review) | compare-and-set on an immutable marker; lines only after a successful swap; handlers retry (7.2) |
| The gate marked members Waiting in a muster, or in another region, and hook 3 ended them at once (spec review) | the gate says go for a committed force and marks only members in the rendezvous region (3.4) |

## Appendix B. Deferred: battleground waves (a later stage)

The owner, 2026-10-13: "focus more on the bots waiting so they are worth rps and then sprinkle in the wave stuff
later, like during the commander phase". This appendix keeps what was worked out, for that stage. Nothing here is
built in stage 1.

- **The owner's choice:** a sliding wave, on "which ever is more likely to have bots go in a group". A realm's
  battleground bots due less than 30 s after the first of them leave together, when the last of them is due; a bot
  alone leaves at its own moment, and none waits 30 s or more past it. Fixed 30 s marks of the clock were the other
  option (two bots due 5 s apart across a mark leave 30 s apart).
- **The simulation** (research `rp-wave-sim-2026-10-13`: `README.md`, `sim.py`, `results.txt`): over three made-up
  mixes of fights, the sliding wave left 1.7-10.8% of bots to go alone against 4.9-18.2% for fixed marks, kept 56-97%
  of pairs killed in one fight together against 46-87%, and added 4.7-11.3 s of wait on average against 15 s. The
  model leaves out bots that drop out of a wave.
- **A first design, per bot.** Each bot recomputed the whole partition from its realm-mates' markers on its turns. The
  first review (`review1-findings.txt`, 17 findings confirmed) showed that waves then re-form whenever an earlier bot
  drops out (killed after leaving, a straggler still fighting, uneven memory of who left), splitting later waves.
- **A second design, per bot with stored anchors.** Each bot took a wave's anchor once and stored it in its marker;
  played out turn by turn (`online.py`) it matched the simulation when nothing drops out, once recently-left anchors
  stayed joinable. The second review, stopped when the owner deferred waves (`review2-partial.md`), still found
  splits: brains think in parallel, so two bots can take anchors from the same stale view in one tick; anchors follow
  the order of first turns, not of dues, when a turn is taken; an anchor can vanish when its holders drop out.
- **What the later stage should try first:** one coordinator per battleground and realm that forms each wave under a
  lock, as the warband gate does under the coordinator lock (3.4), instead of each bot deciding alone. The realm
  commander (roadmap part 7) may want to time pushes anyway.
- **What stage 1 leaves in place for it:** a marker per bot swapped by compare-and-set (2.4, 7.2); `LeaveTick`, each
  bot's own moment (7.1); hook 1 at the battleground arrival point (3.1), where a wave would hold its bots; the
  `leave` log line, to which a wave size can be added (10.5).

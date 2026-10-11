# Quest indicators: one scheme for every quest (design)

Status: the design was approved by the owner in conversation on 2026-10-10; this written spec awaits the owner's review.
Date: 2026-10-11. Fork: `lometur/HearthDAoC`. Branch: `quest-indicators`. Release: merging the PR publishes the next
release; the server picks it up with `./hdc update`. No world data changes.

References are to HearthDAoC `main` at 09b76ef (v0.35b-hearth.10), `source/server/GameServer/` unless a path says
otherwise. Research: `~/Games/DAoC/research/quest-indicators-2026-10-10/findings.md` on the owner's machine (raw pages
stay out of the repo).

## 1. Goal

Every NPC shows one marker, from one set of rules, that tells a player what it has for them: a quest to take, the next
step of a quest they're on, or a quest to turn in. And the marker is always current: it changes the moment the
player's level, class or quests change.

### What is wrong today

- **Two styles for one meaning.** The server's "available" draws a yellow ring at the feet; "finish" draws a blue knot
  over the head. Players see both on quest givers and can't tell why.
- **Stale markers.** A marker is worked out when an NPC comes into view, and again only after a few quest events.
  Nothing re-checks it when a player levels up, changes class, or gets a quest unlocked elsewhere, or after `/epic`.
  The owner's case: a new Infiltrator in Caer Gothwaite, `/player level 7`, `/epic goto` to Elaru: no marker until a
  new login.
- **Nothing for the middle of a quest.** The server has no marker for "see me for your current step".
- **Misleading markers.** Atlas master trainers (17 in the world) and the buff merchant (1) always send "lore", which
  the client draws as a yellow knot, though they give no quests. A quest whose last step is "kill X" (87 quests, e.g. level
  5 "Cleric Mulgrut") puts the blue "turn in" knot on the monster (Mulgrut Maggot).

### What the client draws (owner's test with `/indicator`, 2026-10-10)

| Wire value | Name in the code (`eQuestIndicator`) | Drawn by the 1.127 client |
|---|---|---|
| 1 | Available | yellow ring at the feet (the patch 1.73 indicator, 2004-12-07) |
| 2 | Finish | blue knot over the head |
| 4 | Lesson | yellow book over the head |
| 8 | Lore | yellow knot over the head |
| 16 | Pending | white knot over the head |

Both routes draw the same: the NPC create packet (flags) and the quest effect packet (VisualEffect 0x7).

### Decisions (owner, 2026-10-10)

- **Scheme A, the later retail knots.** Yellow knot = a quest to take; white knot = see me for your current step; blue
  knot = turn in. The Herald's beginner's guide: "NPC characters with an available quest will have a yellow DAoC knot
  floating over their head. The DAoC knot will float over NPCs who also have a completed quest you can turn in (blue
  knot), or if they have further information or steps for the quest (white knot)." The ring and the book are not used.
- **The 1.73 level rule stays:** no yellow knot for a quest whose minimum level is more than 15 below the player's
  level ("If the player is more than 15 levels above the quest's minimum level, the yellow indicator will not be
  displayed on the NPC").
- **Markers update at once** when the player's level, class or quests change.

### Non-goals

- No change to who can take a quest, or to any quest's steps; the 15-level rule hides only the marker.
- No white knot for scripted (C#) quests: they don't expose their current step's target in a general way. They keep the
  yellow knot to start and whatever their own code sends.
- No markers on objects (only NPCs carry them), and none for search steps.
- No client change.

## 2. What players see

| Marker | When an NPC shows it to a player |
|---|---|
| Yellow knot | It offers a quest the player can take now (class, level range, earlier quests), whose minimum level is at most 15 below the player's level. Data quests that start by talking (Standard, AutoStart, RewardQuest start types) and scripted quests. |
| White knot | It is the target of the player's current step of a data quest, and that step is talking, whispering, delivering or bringing items to it (Interact, Whisper, Deliver, Collect), not the last step. |
| Blue knot | It is the target of the last step of a data quest the player is on, and that step is talking, whispering, delivering or bringing items to it (InteractFinish, WhisperFinish, DeliverFinish, CollectFinish); or it gave the player a reward quest whose goals are all done (as today). |
| Nothing | Otherwise. Also: monsters a step says to kill (Kill, KillFinish), one-time drops (KillComplete), item turn-in "collection" quests (Collection), quests started by touching an object or searching (InteractComplete, SearchStart), and NPCs with no quests (Atlas master trainers, the buff merchant). |

**Several at once:** blue, then white, then yellow. What you can finish beats what you're doing, which beats something
new.

**Bounty masters, faction emissaries and the Sluaghbinder trainer** keep their own rules, and their "available" and
"finish" show as the yellow and blue knots like everyone else's.

**When it changes:** at once, for every NPC the player can see, whenever the player's level or class changes, or a
quest is accepted, advanced, finished or abandoned, or `/epic done`/`reset` changes their quests. NPCs coming into view
get the same rules (as at login).

Examples (Guild of Shadows, Shrouded Isles start):
- A new level-7 Infiltrator in Caer Gothwaite: Elaru has a yellow knot.
- After accepting "Strange Beings": Elaru's knot goes; Tage has a white knot.
- On the last step: Adam Glaze has a blue knot. After turning in, Elaru's yellow knot is back at level 11 for "Shades
  and Shadows", or as soon as the character reaches 11.
- A level-30 character passing Elaru sees no knot for the level-7 quest (more than 15 levels above).

## 3. How it works

### 3.1 Meaning and wire value

`GameNPC.GetQuestIndicator` and the classes that override it keep returning `eQuestIndicator` values, now read as
meanings: Available = a quest to take, Pending = see me for your current step, Finish = turn in, None. One table in a
fork file (`scripts/hearthdaoc/QuestIndicators.cs`) turns a meaning into the value the client gets:

| Meaning | Wire value | Drawn |
|---|---|---|
| Available | 8 (Lore) | yellow knot |
| Pending | 16 (Pending) | white knot |
| Finish | 2 (Finish) | blue knot |
| Lore, Lesson, None | 0 | nothing |

It is applied in the two writers the 1.127 client uses: `PacketLib1124.SendNPCCreate` (the create flags) and
`PacketLib173.SendNPCsQuestEffect` (the effect byte), one marked block each. So every caller, upstream's and ours, gets
the scheme without change: the overrides that return Available or Finish show yellow or blue knots, and the Atlas master
trainers' and buff merchant's "lore" shows nothing, with no change to their files.

`/indicator create` and `/indicator effect` stay probes: they send the raw wire value, past the table. `/indicator`
(show) names both the meaning and what is drawn.

### 3.2 The rules (`GameNPC.GetQuestIndicator`, upstream file)

The fork's block in `GetQuestIndicator` (after the `/indicator` override) calls one pure function,
`QuestIndicators.For(...)`, with what it needs from the NPC and the player, and returns its meaning:

1. **Finish** if a data quest in the player's journal is on a step of type DeliverFinish, InteractFinish,
   WhisperFinish or CollectFinish whose target is this NPC (name compared with `QuestNames.Same`, region 0 or this
   region, as `CanFinishOneQuest` does today), or a `RewardQuest` from this NPC has all goals done. KillFinish no longer
   counts.
2. **Pending** if a data quest in the journal is on a step of type Deliver, Interact, Whisper or Collect whose target is
   this NPC (same comparison).
3. **Available** if the NPC offers a quest the player qualifies for (`CanShowOneQuest`'s checks, unchanged), whose
   minimum level is no more than 15 below the player's level: a data quest's `MinLevel`, a scripted quest's `Level`.
4. **None** otherwise.

`CanShowOneQuest` and `CanFinishOneQuest` stay for their other callers; the indicator no longer uses them directly.

### 3.3 Keeping markers current

- **What is known:** the player's `NpcUpdateCache` holds the NPCs the client has. A per-player map (fork file) holds
  the wire value last sent for each of them: set by the create packet's block (3.1) and by every effect sent, cleared
  with the cache.
- **Refresh:** `QuestIndicators.Refresh(player)` asks for a refresh; at most once per game-loop tick per player, it
  works out each known NPC's value and sends the effect packet only where it differs from the last one sent.
- **Who asks** (marked `// HearthDAoC:` one-line calls in upstream files):
  - `GamePlayer.Level` setter, on any change (level up, `/player level` up or down);
  - the class change (`/player class`, trainer promotion);
  - `GamePlayer.AddQuest`;
  - `AbstractQuest.Step` setter, `FinishQuest` and `AbortQuest`, and the overrides in `DataQuest` and `RewardQuest`
    where they don't call the base;
  - `EpicCommand` after `done` and `reset` (it changes the finished list directly).
- Upstream's own scattered `UpdateQuestIndicator`/`SendNPCsQuestEffect` calls stay; they now go through the table and
  the last-sent map, so they agree with the refresh.

### 3.4 Open point from the owner's test

`/mob refreshquests` on Elaru drew nothing, though `/indicator effect 1` drew the ring. Find out why while building
(it calls `LoadDataQuests(player)` before the effect) and say so in the PR; the refresh above doesn't depend on it.

## 4. Testing

### 4.1 C# unit tests (CI)

- `QuestIndicators.For`: each row of section 2, the priority order, the 15-level rule at 15 and 16 levels above, Kill
  and KillFinish targets get nothing, name compared without case, region 0 and other regions.
- The meaning-to-wire table, including Lore and Lesson to nothing.
- Refresh: only changed values are sent; several requests in one tick send once; a cleared cache sends nothing.
- `/indicator`: create and effect stay raw; show names meaning and drawing.
- New test classes added to CI's list.

### 4.2 Source checks (Python, `deploy/tests`)

The marked blocks exist in `GameNPC.cs`, `PacketLib1124.cs`, `PacketLib173.cs`, `GamePlayer.cs`, `AbstractQuest.cs`
and the `DataQuest`/`RewardQuest` overrides that need them, and the refresh calls in `EpicCommand.cs`.

### 4.3 In game (owner, after merge)

1. New Infiltrator in Caer Gothwaite, `/player level 7`: Elaru gets a yellow knot without a new login.
2. Accept "Strange Beings": Elaru's knot goes, Tage shows a white knot; each next step's NPC turns white as the quest
   moves; the last NPC (Adam Glaze) blue; after turning in, Elaru's yellow knot at level 11.
3. A level-30 character near Elaru: no knot.
4. An Atlas master trainer: no knot.
5. "Cleric Mulgrut" (Hugh Gallen, level 5, Albion), on its last step: no blue knot on Mulgrut Maggot.
6. `/epic reset`, then `/epic done 15`: markers around you change at once.

## 5. Upstream, later

Candidates for #49, only with the owner's go-ahead: the refresh on level and quest changes (upstream has the same
stale markers); the KillFinish fix. The scheme itself is the fork's choice.

## 6. Documentation

FORK.md rows for the new file and each upstream file's block; `docs/fork/verification/sub4-test-guide.md` section 4
gains the in-game checks of 4.3.

## 7. Found while reading, separate

`GamePlayer.AddQuest` starts with `if (QuestList.Count > 25)` followed by no statement of its own, so the next `if`
becomes its body and the journal limit is never applied. Filed as #112 (upstream candidate).

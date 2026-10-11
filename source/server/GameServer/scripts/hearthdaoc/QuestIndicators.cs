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
                case RewardQuest rewardQuest when RewardDone(rewardQuest.QuestGiver == npc, rewardQuest.Goals.Select(g => g.IsAchieved)):
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
            yield return ScriptedOffer(ScriptedMinLevel(quest), quest.CheckQuestQualification(player),
                player.HasFinishedQuest(type), player.IsDoingQuest(type) != null, quest.MaxQuestCount);
        }
        foreach (DataQuest quest in offered)
        {
            if (DataOffer(quest.ShowIndicator, quest.Level, () => quest.CheckQuestQualification(player), out QuestOffer offer))
                yield return offer;
        }
    }

    // A scripted quest is offered while the times it was finished, plus the one being done, stay under its
    // MaxQuestCount (GameNPC.CanShowOneQuest).
    public static QuestOffer ScriptedOffer(int? minLevel, bool qualifies, int finished, bool doing, int maxCount) =>
        new(minLevel, qualifies && finished + (doing ? 1 : 0) < maxCount);

    // A data quest is an offer only when it shows a marker (ShowIndicator); only then is it asked to qualify, as
    // upstream: a Collection quest's check reads the database.
    public static bool DataOffer(bool showIndicator, int minLevel, Func<bool> qualifies, out QuestOffer offer)
    {
        offer = showIndicator ? new QuestOffer(minLevel, qualifies()) : default;
        return showIndicator;
    }

    // A reward quest turns in at its own giver once every goal is done; another giver's goals are not read.
    public static bool RewardDone(bool ownGiver, IEnumerable<bool> goalsAchieved) => ownGiver && goalsAchieved.All(done => done);

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

    // /indicator's values stay raw: the byte of /indicator effect (rawEffect: SendRawEffect is sending it), and the
    // /indicator create value the GM set on this NPC (forced), which GameNPC.GetQuestIndicator returns.
    public static bool IsRaw(bool rawEffect, bool forced) => rawEffect || forced;

    // The value is the GM's /indicator create value for this NPC (a class that ignores it gives its own value, which
    // goes through the table).
    private static bool Forced(GamePlayer player, GameNPC npc, eQuestIndicator value) =>
        IndicatorOverrides.TryGet(player, npc, out eQuestIndicator forced) && forced == value;

    // The value a packet writer puts on the wire for this player and NPC.
    public static eQuestIndicator WireFor(GamePlayer player, GameNPC npc, eQuestIndicator value) =>
        ToWire(value, IsRaw(t_raw, Forced(player, npc, value)));

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

    public static readonly IndicatorSentStore LastSent = new();

    private static readonly Logger Log = LoggerManager.Create(typeof(QuestIndicators));

    // Called by the quest effect's writer (PacketLib173.SendNPCsQuestEffect) with the value it was given: returns the
    // value to send, recorded as the last one sent to the player for the NPC.
    public static eQuestIndicator Sending(GamePlayer player, GameNPC npc, eQuestIndicator value)
    {
        eQuestIndicator wire = WireFor(player, npc, value);
        LastSent.Record(player, npc, (byte)wire, new SentPlace(npc.ObjectID, npc.CurrentRegionID));
        return wire;
    }

    // Called by the create packet's writer (PacketLib1124.SendNPCCreate): as Sending, but a value that differs from the
    // last one sent, or a create under an object ID another NPC was sent under, also asks a refresh, whose quest effect
    // draws it even on a client that still had an object under that ID; not for a GM's /indicator create value, whose
    // create alone is what the GM is looking at (IndicatorSentStore.RecordCreate).
    public static eQuestIndicator SendingCreate(GamePlayer player, GameNPC npc, eQuestIndicator value)
    {
        bool forced = Forced(player, npc, value);
        eQuestIndicator wire = ToWire(value, IsRaw(t_raw, forced));
        if (LastSent.RecordCreate(player, npc, (byte)wire, new SentPlace(npc.ObjectID, npc.CurrentRegionID), forced))
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

        // Values sent in another region are dropped; an NPC that left the world is marked unknown, so its marker is sent
        // again when it comes back (IndicatorSentStore.Prune). Only active NPCs in this region are asked.
        ushort region = player.CurrentRegionID;
        LastSent.Prune(player, region, o => o is GameNPC npc && npc.ObjectState == GameObject.eObjectState.Active,
            o => ((GameNPC)o).CurrentRegionID);
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

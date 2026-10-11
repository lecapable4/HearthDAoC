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

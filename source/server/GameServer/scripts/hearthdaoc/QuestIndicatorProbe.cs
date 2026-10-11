using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading;
using DOL.GS.Quests;

namespace DOL.GS.HearthDAoC;

// HearthDAoC: the GM's /indicator command, a probe for the quest indicators. The server shows an NPC's indicator two
// ways: in the NPC create packet (PacketLib1124.SendNPCCreate: flags2 0x08 available, 0x10 finish; flags3 0x01
// lesson, 0x02 lore, 0x20 pending) and in the quest effect (PacketLib173.SendNPCsQuestEffect: the indicator byte).
// This file holds every decision: reading the arguments, the per-(GM, NPC) store of forced indicators, and the plain
// words for why an NPC shows what it shows. It reads nothing from the running server, so unit tests drive it
// directly; IndicatorCommand gathers the facts and sends the packets.

public enum IndicatorAction { Show, Effect, Create, Clear, Refresh, Syntax }

// What "/indicator ..." asks for. Effect: the raw byte; Create: the indicator; Error: why the arguments are wrong.
public sealed record IndicatorRequest(IndicatorAction Action, byte Effect = 0,
    eQuestIndicator Indicator = eQuestIndicator.None, string Error = null);

// A data quest the NPC gives. Qualifies is DataQuest.CheckQuestQualification's answer; the other fields say why not.
// DoneMaxTimes: finished as many times as it can be. Dependency: the QuestDependency entries as stored.
public sealed record GivenDataQuest(int Id, string Name, string StartType, bool ShowsIndicator, bool Qualifies,
    int MinLevel, int MaxLevel, bool ClassAllowed, bool Doing, bool DoneMaxTimes, bool DependenciesMet,
    string Dependency);

// A scripted quest the NPC gives. Qualifies is the quest's CheckQuestQualification; it shows only while the times
// finished and the one being done stay under MaxCount (GameNPC.CanShowOneQuest). MinLevel: its Level when its class
// declares one (QuestIndicators.ScriptedMinLevel), else null.
public sealed record GivenScriptedQuest(string Name, bool Qualifies, int Finished, bool Doing, int MaxCount,
    int? MinLevel = null);

// A data quest of the player's whose current step targets this NPC.
public sealed record StepAtNpc(int QuestId, string QuestName, int Step, DataQuest.eStepType StepType);

// Everything the "why" needs. RewardQuestsDone: the player's reward quests from this NPC with every goal done.
// OverridingClass: the NPC's class when it overrides GetQuestIndicator, else null. Actual: what GetQuestIndicator
// gives this player, without /indicator's override. Forced: this GM's /indicator create value on the NPC, if any.
public sealed record IndicatorFacts(int Level, IReadOnlyList<GivenDataQuest> DataQuests,
    IReadOnlyList<GivenScriptedQuest> ScriptedQuests, IReadOnlyList<StepAtNpc> StepsHere,
    IReadOnlyList<string> RewardQuestsDone, string OverridingClass, eQuestIndicator Actual,
    eQuestIndicator? Forced = null);

public static class QuestIndicatorProbe
{
    // The names /indicator create takes, in eQuestIndicator's order.
    public static readonly IReadOnlyList<string> Names = new[] { "none", "available", "finish", "lesson", "lore", "pending" };

    private static readonly IReadOnlyDictionary<string, eQuestIndicator> ByName =
        new Dictionary<string, eQuestIndicator>(StringComparer.OrdinalIgnoreCase)
        {
            ["none"] = eQuestIndicator.None,
            ["available"] = eQuestIndicator.Available,
            ["finish"] = eQuestIndicator.Finish,
            ["lesson"] = eQuestIndicator.Lesson,
            ["lore"] = eQuestIndicator.Lore,
            ["pending"] = eQuestIndicator.Pending,
        };

    // The start types whose quests never show an indicator (DataQuest.ShowIndicator); any other hides it only with
    // NO_INDICATOR in its SourceName.
    private static readonly IReadOnlySet<string> HiddenStartTypes =
        new HashSet<string> { "Collection", "KillComplete", "InteractComplete", "SearchStart" };

    public static string CreateNeeds => "create needs one of: " + string.Join(", ", Names);

    public const string EffectNeeds = "effect needs a byte, 0 to 255 (or 0x00 to 0xFF)";

    // args as a command gets them: args[0] is "&indicator".
    public static IndicatorRequest Parse(string[] args)
    {
        if (args.Length < 2)
            return new IndicatorRequest(IndicatorAction.Show);
        switch (args[1].ToLowerInvariant())
        {
            case "show":
                return new IndicatorRequest(IndicatorAction.Show);
            case "clear":
                return new IndicatorRequest(IndicatorAction.Clear);
            case "refresh":
                return new IndicatorRequest(IndicatorAction.Refresh);
            case "effect":
                return args.Length > 2 && TryParseByte(args[2], out byte value)
                    ? new IndicatorRequest(IndicatorAction.Effect, Effect: value)
                    : new IndicatorRequest(IndicatorAction.Effect, Error: EffectNeeds);
            case "create":
                return args.Length > 2 && ByName.TryGetValue(args[2], out eQuestIndicator indicator)
                    ? new IndicatorRequest(IndicatorAction.Create, Indicator: indicator)
                    : new IndicatorRequest(IndicatorAction.Create, Error: CreateNeeds);
            default:
                return new IndicatorRequest(IndicatorAction.Syntax);
        }
    }

    public static bool TryParseByte(string text, out byte value)
    {
        if (text.StartsWith("0x", StringComparison.OrdinalIgnoreCase))
            return byte.TryParse(text.AsSpan(2), NumberStyles.AllowHexSpecifier, CultureInfo.InvariantCulture, out value);
        return byte.TryParse(text, NumberStyles.None, CultureInfo.InvariantCulture, out value);
    }

    public static string Name(eQuestIndicator indicator) => indicator switch
    {
        eQuestIndicator.None => "none",
        eQuestIndicator.Available => "available",
        eQuestIndicator.Finish => "finish",
        eQuestIndicator.Lesson => "lesson",
        eQuestIndicator.Lore => "lore",
        eQuestIndicator.Pending => "pending",
        _ => $"0x{(byte)indicator:X2}",
    };

    // The bit PacketLib1124.SendNPCCreate sets for the indicator.
    public static string CreateFlag(eQuestIndicator indicator) => indicator switch
    {
        eQuestIndicator.Available => "flags2 0x08",
        eQuestIndicator.Finish => "flags2 0x10",
        eQuestIndicator.Lesson => "flags3 0x01",
        eQuestIndicator.Lore => "flags3 0x02",
        eQuestIndicator.Pending => "flags3 0x20",
        _ => "no flag",
    };

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
        if (quest.ShowsIndicator)
            return why;
        string hidden = HiddenStartTypes.Contains(quest.StartType) ? $"a {quest.StartType} quest" : "NO_INDICATOR";
        return $"{why}; never shows an indicator ({hidden})";
    }

    private static string WhyNot(GivenDataQuest quest, int level)
    {
        if (level < quest.MinLevel)
            return $"needs level {quest.MinLevel}";
        if (level > quest.MaxLevel)
            return $"only to level {quest.MaxLevel}";
        if (!quest.ClassAllowed)
            return "not for your class";
        if (quest.Doing)
            return "you are doing it";
        if (quest.DoneMaxTimes)
            return "already done";
        if (!quest.DependenciesMet)
            return $"dependencies {quest.Dependency} not met";
        return "its custom step check refuses";
    }

    public static string Why(GivenScriptedQuest quest, int level = 0)
    {
        if (Shows(quest))
            return TooLow(quest.MinLevel, level) ? TooLowText(quest.MinLevel.Value) : "qualifies";
        if (!quest.Qualifies)
            return "its own check refuses";
        return quest.Doing ? "you are doing it" : "already done";
    }

    // The lines /indicator show prints: the indicator and why, then every quest the first line doesn't name, then
    // the NPC's class if it decides its own indicator.
    public static IReadOnlyList<string> Explain(IndicatorFacts facts)
    {
        var lines = new List<string>();
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
            named = (object)scripted ?? data;
            reason = (scripted != null ? $"scripted quest {scripted.Name}" : $"data quest {data.Id} {data.Name}") +
                " (qualifies)" + (count > 1 ? $" and {count - 1} more" : string.Empty);
        }
        else if (rules == eQuestIndicator.Finish)
        {
            StepAtNpc step = facts.StepsHere.FirstOrDefault(s => Finishes(s.StepType));
            named = step;
            reason = step != null
                ? $"data quest {step.QuestId} step {step.Step} targets this NPC"
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
            foreach (GivenDataQuest quest in facts.DataQuests.Where(q => !ReferenceEquals(q, named)))
                lines.Add($"  data quest {quest.Id} {quest.Name}: {Why(quest, facts.Level)}");
        }
        foreach (string quest in facts.RewardQuestsDone.Skip(named == null && rules == eQuestIndicator.Finish ? 1 : 0))
            lines.Add($"  reward quest {quest} has every goal done");
        foreach (StepAtNpc step in facts.StepsHere.Where(s => !ReferenceEquals(s, named)))
            lines.Add($"  your data quest {step.QuestId} {step.QuestName} is at step {step.Step} ({step.StepType}) here" +
                (Finishes(step.StepType) || Pends(step.StepType) ? string.Empty : ", a step that shows no marker"));
        if (facts.OverridingClass != null)
            lines.Add($"  {facts.OverridingClass} overrides GetQuestIndicator" +
                (facts.Actual == rules ? "; here it agrees with GameNPC's rules" : string.Empty));
        return lines;
    }

    private static string NoneReason(IndicatorFacts facts)
    {
        int data = facts.DataQuests.Count, scripted = facts.ScriptedQuests.Count;
        if (data + scripted == 0)
            return "this NPC gives no quests, and no quest of yours finishes here";
        var counts = new List<string>();
        if (data > 0)
            counts.Add(data == 1 ? "1 data quest" : $"{data} data quests");
        if (scripted > 0)
            counts.Add(scripted == 1 ? "1 scripted quest" : $"{scripted} scripted quests");
        IEnumerable<string> why = facts.ScriptedQuests.Select(q => $"{q.Name}: {Why(q, facts.Level)}")
            .Concat(facts.DataQuests.Select(q => $"{q.Id}: {Why(q, facts.Level)}"));
        return $"{string.Join(" and ", counts)}, none qualifies ({string.Join("; ", why)})";
    }
}

// The indicators /indicator create forces, one per (GM, NPC), compared by reference. Read for every NPC create
// packet, so a lookup on an empty store takes no lock.
public sealed class IndicatorOverrideStore
{
    private readonly Lock _lock = new();
    private readonly Dictionary<(object Gm, object Npc), eQuestIndicator> _entries = new(KeyComparer.Instance);
    private volatile int _count;

    public int Count => _count;

    public void Set(object gm, object npc, eQuestIndicator indicator)
    {
        lock (_lock)
        {
            _entries[(gm, npc)] = indicator;
            _count = _entries.Count;
        }
    }

    public bool TryGet(object gm, object npc, out eQuestIndicator indicator)
    {
        indicator = eQuestIndicator.None;
        if (_count == 0)
            return false;
        lock (_lock)
            return _entries.TryGetValue((gm, npc), out indicator);
    }

    public bool Remove(object gm, object npc)
    {
        lock (_lock)
        {
            bool removed = _entries.Remove((gm, npc));
            _count = _entries.Count;
            return removed;
        }
    }

    // Drops every entry of the GM; returns their NPCs.
    public List<object> RemoveGm(object gm)
    {
        lock (_lock)
        {
            List<object> npcs = _entries.Keys.Where(k => ReferenceEquals(k.Gm, gm)).Select(k => k.Npc).ToList();
            foreach (object npc in npcs)
                _entries.Remove((gm, npc));
            _count = _entries.Count;
            return npcs;
        }
    }

    // Drops every GM's entry for the NPC; returns how many.
    public int RemoveNpc(object npc)
    {
        if (_count == 0)
            return 0;
        lock (_lock)
        {
            List<(object Gm, object Npc)> keys = _entries.Keys.Where(k => ReferenceEquals(k.Npc, npc)).ToList();
            foreach ((object Gm, object Npc) key in keys)
                _entries.Remove(key);
            _count = _entries.Count;
            return keys.Count;
        }
    }

    public void Clear()
    {
        lock (_lock)
        {
            _entries.Clear();
            _count = 0;
        }
    }

    private sealed class KeyComparer : IEqualityComparer<(object Gm, object Npc)>
    {
        public static readonly KeyComparer Instance = new();

        public bool Equals((object Gm, object Npc) x, (object Gm, object Npc) y) =>
            ReferenceEquals(x.Gm, y.Gm) && ReferenceEquals(x.Npc, y.Npc);

        public int GetHashCode((object Gm, object Npc) key) =>
            HashCode.Combine(RuntimeHelpers.GetHashCode(key.Gm), RuntimeHelpers.GetHashCode(key.Npc));
    }
}

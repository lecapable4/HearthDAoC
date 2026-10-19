using System.Collections.Generic;

namespace DOL.GS.Quests;

// HearthDAoC: what our hearthdaoc-quests.json entry carries onto upstream's classic-quests.json entry for the same quest
// ID when it is not a Replace entry (ClassicQuests.Merge; the 0.37 sync, #138). Upstream 0.36 added two per-quest fields
// the fork sets without rebuilding a quest: XpShares (each stage's XP as a share of the player's current level,
// ClassicQuests.ScaleXP) and a step's Greet (what the step's NPC says when the player comes back to it). The owner's Guild
// of Shadows rule (a quarter of a level for steps 7 and 11, a tenth from 15 on: decision 1.c) goes onto upstream's
// entries this way, and level 43's greeting on the wrong stage is dropped (R6).

/// <summary>Our entry's XpShares and Greets, laid onto upstream's entry for the same quest.</summary>
public static class ClassicQuestOverlay
{
    /// <summary>
    /// Changes <paramref name="upstream"/> in place. Our <c>XpShares</c>, when it lists any, replaces upstream's list
    /// (omitted, null or empty keeps upstream's; a share of 0 pays the row's fixed RewardXP). Each of our steps'
    /// <c>Greet</c> replaces upstream's greeting on that step: "" removes it, null (or no step) keeps it, and a step
    /// upstream's entry has no info for is added with only the greeting. Nothing else of ours is read: a marker, an item
    /// or a custom step of ours needs a Replace entry. A null entry on either side changes nothing.
    /// </summary>
    public static void Apply(ClassicQuests.QuestInfo upstream, ClassicQuests.QuestInfo ours)
    {
        if (upstream == null || ours == null)
            return;

        if (ours.XpShares is { Count: > 0 })
            upstream.XpShares = new List<double>(ours.XpShares);

        if (ours.Steps == null)
            return;

        for (int i = 0; i < ours.Steps.Count; i++)
        {
            string greet = ours.Steps[i]?.Greet;
            if (greet == null)
                continue;

            upstream.Steps ??= new List<ClassicQuests.StepInfo>();
            if (greet.Length == 0)
            {
                if (i < upstream.Steps.Count && upstream.Steps[i] != null)
                    upstream.Steps[i].Greet = null;
                continue;
            }

            while (upstream.Steps.Count <= i)
                upstream.Steps.Add(null);
            (upstream.Steps[i] ??= new ClassicQuests.StepInfo()).Greet = greet;
        }
    }
}

using System;
using System.Collections.Generic;
using System.Linq;
using DOL.AI.Brain;
using DOL.Events;
using DOL.GS.Quests;

namespace DOL.GS.HearthDAoC;

// HearthDAoC (#119, owner 2026-10-13): linked quest camps. In the period some quest targets fought with their camp:
// "she is by the fire, linked to 2 rangers" (Delfina, 2002); "if you pull a guard from next to the tower sir dillius
// will come too" (2002); "The courier is next to the tent and he is linked to the two by the fire" (2002); "Savant and
// pet attack at the same time" (2003). The server's own Bring a Friend is off for solo players (baf_initial_chance 0)
// and pulls any nearby mob of the faction; these are named camps. The groups are in hearthdaoc-quests.json ("Links",
// ClassicQuests.Links): when a caller is attacked, the camp's other members that stand within its range, alive and
// not fighting yet, join the fight against its attacker, players, pets and gamebots alike. Upstream files are not
// touched: the server notifies GameLivingEvent.AttackedByEnemy for every attack, and this listens.
public static class LinkedCamps
{
    /// <summary>The members of <paramref name="group"/> that join a fight against whoever attacked
    /// <paramref name="attackedId"/>: none unless it is a member and a caller (no callers: every member calls); then every
    /// other member in <paramref name="others"/> that is available (alive, in the world, not fighting yet)
    /// and within the group's range of it, in the group's order.</summary>
    public static IReadOnlyList<string> Joiners(ClassicQuests.LinkGroup group, string attackedId,
        IReadOnlyDictionary<string, (bool Available, double Distance)> others)
    {
        if (group?.Members == null || attackedId == null || !group.Members.Contains(attackedId))
            return Array.Empty<string>();
        if (group.Callers is { Count: > 0 } && !group.Callers.Contains(attackedId))
            return Array.Empty<string>();
        return group.Members
            .Where(id => id != attackedId && others.TryGetValue(id, out var m) && m.Available && m.Distance <= group.Range)
            .ToList();
    }

    // The members of every group, by Mob_ID, built again when ClassicQuests loads its files anew: the handler runs for
    // every attack in the game and must leave at once for everyone else.
    private static IReadOnlyList<ClassicQuests.LinkGroup> s_indexed;
    private static Dictionary<string, List<ClassicQuests.LinkGroup>> s_byMember = new();

    private static Dictionary<string, List<ClassicQuests.LinkGroup>> ByMember()
    {
        IReadOnlyList<ClassicQuests.LinkGroup> links = ClassicQuests.Links;
        if (ReferenceEquals(links, s_indexed))
            return s_byMember;
        var byMember = new Dictionary<string, List<ClassicQuests.LinkGroup>>(StringComparer.Ordinal);
        foreach (ClassicQuests.LinkGroup group in links)
            foreach (string id in group?.Members ?? new List<string>())
            {
                if (!byMember.TryGetValue(id, out var groups))
                    byMember[id] = groups = new List<ClassicQuests.LinkGroup>();
                groups.Add(group);
            }
        s_byMember = byMember;
        s_indexed = links;
        return byMember;
    }

    [ScriptLoadedEvent]
    public static void OnScriptLoaded(DOLEvent e, object sender, EventArgs args) =>
        GameEventMgr.AddHandler(GameLivingEvent.AttackedByEnemy, OnAttacked);

    [ScriptUnloadedEvent]
    public static void OnScriptUnloaded(DOLEvent e, object sender, EventArgs args) =>
        GameEventMgr.RemoveHandler(GameLivingEvent.AttackedByEnemy, OnAttacked);

    private static void OnAttacked(DOLEvent e, object sender, EventArgs args)
    {
        if (sender is not GameNPC npc || npc.InternalID == null || args is not AttackedByEnemyEventArgs attacked)
            return;
        if (!ByMember().TryGetValue(npc.InternalID, out var groups))
            return;
        GameLiving attacker = attacked.AttackData?.Attacker;
        if (attacker == null || !attacker.IsAlive || attacker == npc)
            return;
        foreach (ClassicQuests.LinkGroup group in groups)
        {
            var near = new Dictionary<string, (bool, double)>(StringComparer.Ordinal);
            var found = new Dictionary<string, StandardMobBrain>(StringComparer.Ordinal);
            foreach (GameNPC other in npc.GetNPCsInRadius((ushort)Math.Clamp(group.Range, 0, ushort.MaxValue)))
            {
                if (other == npc || other.InternalID == null || !group.Members.Contains(other.InternalID))
                    continue;
                bool available = other.IsAlive && other.ObjectState == GameObject.eObjectState.Active &&
                                 other.Brain is StandardMobBrain brain && !brain.HasAggro;
                near[other.InternalID] = (available, npc.GetDistanceTo(other));
                if (available)
                    found[other.InternalID] = (StandardMobBrain)other.Brain;
            }
            foreach (string id in Joiners(group, npc.InternalID, near))
                found[id].AddToAggroList(attacker); // as Bring a Friend has its adds join
        }
    }
}

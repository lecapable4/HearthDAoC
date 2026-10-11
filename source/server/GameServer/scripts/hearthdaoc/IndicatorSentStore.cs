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

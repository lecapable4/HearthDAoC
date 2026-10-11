using System;
using System.Collections.Generic;
using System.Runtime.CompilerServices;
using System.Threading;

namespace DOL.GS.HearthDAoC;

// HearthDAoC: part of the quest indicators (QuestIndicators.cs; spec docs/fork/specs/2026-10-11-quest-indicators-design.md,
// section 3.3).

// Where a client knows an NPC: the object ID and region it was sent under (a client knows objects by ID).
public readonly record struct SentPlace(int ObjectId, ushort Region);

// The wire value each player's client was last sent for each NPC, by the create packet's flags or the quest effect,
// with where the client knows it, and whether a refresh is queued for the player. Players and NPCs compare by
// reference; a player's values go with the player object, and at its Quit. No value means 0 (nothing drawn), so only
// NPCs that show a marker take room. It reads nothing from the running server, so unit tests drive it with plain
// objects.
public sealed class IndicatorSentStore
{
    private readonly record struct Sent(byte Wire, SentPlace Place);

    private sealed class PlayerSent
    {
        // A leaf lock: held only around Wire.
        public readonly Lock Lock = new();
        public readonly Dictionary<object, Sent> Wire = new(ReferenceEqualityComparer.Instance);
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
            return sent.Wire.TryGetValue(npc, out Sent value) ? value.Wire : (byte)0;
    }

    // A value no client draws: "unknown", so the next refresh sends the real one.
    public const byte Unknown = 0xFF;

    // What the quest effect's writer just sent to the player's client for the NPC, known there by place.
    public void Record(object player, object npc, byte wire, SentPlace place) => Record(player, npc, wire, (SentPlace?)place);

    // What a refresh just sent: the writer has recorded the place already, which this keeps.
    public void Record(object player, object npc, byte wire) => Record(player, npc, wire, null);

    private void Record(object player, object npc, byte wire, SentPlace? place)
    {
        PlayerSent sent;
        if (wire != 0)
            sent = For(player);
        else if (!_players.TryGetValue(player, out sent))
            return;
        lock (sent.Lock)
            Set(sent, npc, wire, place);
    }

    private static void Set(PlayerSent sent, object npc, byte wire, SentPlace? place)
    {
        if (wire == 0)
        {
            sent.Wire.Remove(npc);
            return;
        }
        SentPlace kept = place ?? (sent.Wire.TryGetValue(npc, out Sent old) ? old.Place : default);
        sent.Wire[npc] = new Sent(wire, kept);
    }

    // What a create packet just carried, for an NPC the client knows by place. A client that still has an object under
    // that ID (an NPC out of the server's range lingers on the client; one killed out of range was never removed there)
    // may take the create as an update and keep its old drawing. So, unless it is a GM's /indicator create value (probe:
    // the create alone is what the GM is looking at), a value that differs from the last one sent for this NPC, or a
    // create under an ID another NPC was sent under in that region, is recorded as Unknown and the caller asks a refresh,
    // whose quest effect draws it. True when that refresh is needed.
    public bool RecordCreate(object player, object npc, byte wire, SentPlace place, bool probe)
    {
        PlayerSent sent = For(player);
        lock (sent.Lock)
        {
            // Object IDs are unique among live objects in a region: another NPC sent under this one is gone.
            bool reused = false;
            List<object> stale = null;
            foreach (KeyValuePair<object, Sent> entry in sent.Wire)
            {
                if (!ReferenceEquals(entry.Key, npc) && entry.Value.Place == place)
                    (stale ??= new List<object>()).Add(entry.Key);
            }
            if (stale != null)
            {
                reused = true;
                foreach (object other in stale)
                    sent.Wire.Remove(other);
            }

            if (probe)
            {
                Set(sent, npc, wire, place);
                return false;
            }
            byte last = sent.Wire.TryGetValue(npc, out Sent value) ? value.Wire : (byte)0;
            if (!reused && last == wire)
            {
                Set(sent, npc, wire, place);
                return false;
            }
            sent.Wire[npc] = new Sent(Unknown, place);
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

    // At a refresh, for a player now in region: drops the values sent in another region (the client dropped those
    // objects at the region change) and of NPCs that moved to another region; marks Unknown the NPCs that left the world
    // (a client out of their range when they died or were removed still draws them, so their marker is sent again when
    // they come back). inWorld and regionOf run under the leaf lock, so they must only read plain fields.
    public void Prune(object player, ushort region, Func<object, bool> inWorld, Func<object, ushort> regionOf)
    {
        if (!_players.TryGetValue(player, out PlayerSent sent))
            return;
        lock (sent.Lock)
        {
            List<object> drop = null, unknown = null;
            foreach (KeyValuePair<object, Sent> entry in sent.Wire)
            {
                if (entry.Value.Place.Region != region)
                    (drop ??= new List<object>()).Add(entry.Key);
                else if (!inWorld(entry.Key))
                {
                    if (entry.Value.Wire != Unknown)
                        (unknown ??= new List<object>()).Add(entry.Key);
                }
                else if (regionOf(entry.Key) != region)
                    (drop ??= new List<object>()).Add(entry.Key);
            }
            if (drop != null)
            {
                foreach (object npc in drop)
                    sent.Wire.Remove(npc);
            }
            if (unknown != null)
            {
                foreach (object npc in unknown)
                    sent.Wire[npc] = sent.Wire[npc] with { Wire = Unknown };
            }
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

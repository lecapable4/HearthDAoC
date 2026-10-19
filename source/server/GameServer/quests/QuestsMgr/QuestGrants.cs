using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;
using DOL.Database;
using DOL.Logging;

namespace DOL.GS.Quests;

// HearthDAoC: a real item a classic quest's step grants is handed once per character and quest (the 0.37 sync, review
// finding data-1). Upstream's ClassicQuests.GrantItems hands a step's granted items (an NPC's hand-over, a named
// monster's drop) to a player on that step who holds none in slots 7-249, once a minute, so that a quest token lost on
// the way can be had again. Upstream's grants hand carried-only tokens; the sync made seven of them the period's
// rewards (deploy/bin/mob_fixes.json, deploy/hearthdaoc-quests.json), and a reward put in the account vault (slot
// 2500 on), sold or destroyed came back every minute, without limit. GrantItems asks HandOnce first, in one marked line.

/// <summary>Hands a real item a quest grants once per character and quest, and remembers it across restarts.</summary>
public static class QuestGrants
{
    /// <summary>The character custom parameter (<see cref="DbCoreCharacterXCustomParam"/>) of a handed grant: one row per
    /// quest and item, the value <see cref="Entry"/>. To hand one again, stop the server first, then delete the row
    /// (deploy/HANDOFF.md): <see cref="CustomParamStore"/> reads a character's rows once and keeps them in memory while
    /// the server runs, so a row deleted then hands nothing until the next start.</summary>
    public const string Key = "hearthdaoc_quest_grant";

    private const int ValueLength = 255; // CustomParam.Value is a VARCHAR(255)

    private static readonly Logger Log = LoggerManager.Create(typeof(QuestGrants));

    /// <summary>Where the handed grants are kept: the character custom parameters at run time.</summary>
    public interface IStore
    {
        bool Has(string owner, string entry);
        void Add(string owner, string entry);
    }

    public enum Outcome
    {
        /// <summary>A quest token: upstream's re-issue hands it, as before.</summary>
        Upstream,
        /// <summary>Handed to this character for this quest before (now or before a restart): never again.</summary>
        AlreadyHanded,
        /// <summary>The player holds one on the step (a copy from before this rule): it counts as handed.</summary>
        Held,
        /// <summary>Handed now, and remembered.</summary>
        Handed,
        /// <summary>The backpack could not take it: nothing is remembered, and a later refresh tries again.</summary>
        NotHanded,
    }

    /// <summary>A quest token: carried only (Item_Type 40, the backpack's first slot: it cannot be worn) and worth
    /// nothing to a merchant. Upstream's carried-only copies are; a reward is not.</summary>
    public static bool IsToken(int itemType, long price) => itemType == (int)eInventorySlot.FirstBackpack && price <= 0;

    /// <summary>"questId:templateId" (the id trimmed and lower case); an id too long for the column is hashed.</summary>
    public static string Entry(int questId, string templateId)
    {
        string id = (templateId ?? string.Empty).Trim().ToLowerInvariant();
        string entry = $"{questId}:{id}";
        if (entry.Length <= ValueLength)
            return entry;

        return $"{questId}:#{Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(id)))}";
    }

    private static readonly ConcurrentDictionary<string, object> Gates = new(StringComparer.Ordinal);

    /// <summary>
    /// The rule. A token is left to upstream. A real item is handed (<paramref name="hand"/>, which returns whether the
    /// backpack took it) only when this character has never been handed it for this quest and does not hold one
    /// (<paramref name="held"/>); handing it or holding one is remembered in <paramref name="store"/>. One character's
    /// grants are decided one at a time, so two refreshes at once hand it once.
    /// </summary>
    public static Outcome Grant(IStore store, string owner, int questId, string templateId, bool token, Func<bool> held, Func<bool> hand)
    {
        if (token)
            return Outcome.Upstream;

        owner ??= string.Empty;
        string entry = Entry(questId, templateId);
        lock (Gates.GetOrAdd(owner, _ => new object()))
        {
            if (store.Has(owner, entry))
                return Outcome.AlreadyHanded;

            if (held())
            {
                store.Add(owner, entry);
                return Outcome.Held;
            }

            if (!hand())
                return Outcome.NotHanded;

            store.Add(owner, entry);
            return Outcome.Handed;
        }
    }

    /// <summary>
    /// GrantItems' hook, for each item a step grants: true when the item is the fork's to hand (handed now, held, or
    /// handed before), so upstream's code skips it; false for a token, an empty id or a template the world lacks, which
    /// upstream's code handles as before.
    /// </summary>
    public static bool HandOnce(GamePlayer player, DataQuest quest, string id, string from)
    {
        if (player == null || quest == null || string.IsNullOrEmpty(id))
            return false;

        DbItemTemplate template = GameServer.Database.FindObjectByKey<DbItemTemplate>(id);
        if (template == null)
            return false;

        Outcome outcome = Grant(CharacterStore, player.ObjectId, quest.ID, template.Id_nb, IsToken(template.Item_Type, template.Price),
            () => player.Inventory.GetFirstItemByID(id, eInventorySlot.Min_Inv, eInventorySlot.Max_Inv) != null,
            () =>
            {
                if (!player.Inventory.AddTemplate(GameInventoryItem.Create(template), 1, eInventorySlot.FirstBackpack, eInventorySlot.LastBackpack))
                    return false;

                // Upstream's words for a grant (GrantItems).
                string giver = string.IsNullOrEmpty(from) ? "You receive" : from + " gives you";
                player.Out.SendMessage($"{giver} {template.GetName(1, false)}.", PacketHandler.eChatType.CT_System, PacketHandler.eChatLoc.CL_SystemWindow);
                return true;
            });
        return outcome != Outcome.Upstream;
    }

    private static readonly IStore CharacterStore = new CustomParamStore();

    /// <summary>The character custom parameters, read once per character and kept in memory. A row that cannot be
    /// written is still remembered until the server stops (as BountyQuest's: a paid reward is never claimable again);
    /// while a character's rows cannot be read, nothing is handed to it (a later refresh reads them again).</summary>
    private sealed class CustomParamStore : IStore
    {
        private readonly ConcurrentDictionary<string, HashSet<string>> _handed = new(StringComparer.Ordinal);

        // Called under the owner's gate (Grant), so one character's set is read and changed by one call at a time.
        private HashSet<string> For(string owner)
        {
            if (_handed.TryGetValue(owner, out HashSet<string> known))
                return known;

            HashSet<string> loaded = Load(owner);
            if (loaded != null)
                _handed[owner] = loaded;
            return loaded;
        }

        private static HashSet<string> Load(string owner)
        {
            try
            {
                var entries = new HashSet<string>(StringComparer.Ordinal);
                foreach (DbCoreCharacterXCustomParam row in DOLDB<DbCoreCharacterXCustomParam>.SelectObjects(
                             DB.Column("DOLCharactersObjectId").IsEqualTo(owner).And(DB.Column("KeyName").IsEqualTo(Key))))
                {
                    if (!string.IsNullOrEmpty(row?.Value))
                        entries.Add(row.Value);
                }
                return entries;
            }
            catch (Exception ex)
            {
                Log.Error($"Could not read the quest grants of {owner}", ex);
                return null;
            }
        }

        public bool Has(string owner, string entry) => For(owner)?.Contains(entry) ?? true;

        public void Add(string owner, string entry)
        {
            if (For(owner)?.Add(entry) == false)
                return;

            try
            {
                GameServer.Database.AddObject(new DbCoreCharacterXCustomParam(owner, Key, entry));
            }
            catch (Exception ex)
            {
                Log.Error($"Could not save the quest grant {entry} of {owner}", ex);
            }
        }
    }
}

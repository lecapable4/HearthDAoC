namespace DOL.GS.Quests
{
    /// <summary>
    /// HearthDAoC (#112): the quest journal's rules, for <c>GamePlayer.AddQuest</c> and the data quests' starts.
    /// Upstream's AddQuest began <c>if (QuestList.Count &gt; 25)</c> with no body, so that line guarded the duplicate check
    /// after it: the journal had no limit, and the duplicate check ran only above 25 quests. And that check compared C#
    /// types, which every data quest shares: for a data quest it meant "on any data quest".
    /// </summary>
    public static class QuestJournal
    {
        /// <summary>The client's journal shows 25 quests (PacketLib168's JOURNAL_MAX_QUEST_COUNT).</summary>
        public const int Capacity = 25;

        public static bool IsFull(int questCount) => questCount >= Capacity;

        /// <summary>Whether two quests are the same quest: data quests by their ID, other quests by their class (one
        /// class per scripted quest).</summary>
        public static bool Same(AbstractQuest a, AbstractQuest b) =>
            a is DataQuest x && b is DataQuest y ? x.ID == y.ID : a.GetType() == b.GetType();
    }
}

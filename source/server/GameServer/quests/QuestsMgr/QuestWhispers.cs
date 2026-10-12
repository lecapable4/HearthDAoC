using System;

namespace DOL.GS.Quests
{
    /// <summary>
    /// HearthDAoC: what a player whispers to a Whisper or WhisperFinish step's target to advance it. Upstream compared
    /// the step's AdvanceText with the whisper exactly, so an AdvanceText with a token the server replaces in what it
    /// sends (<c>&lt;Player&gt;</c>, the player's name: BehaviourUtils.GetPersonalizedMessage) could never be matched.
    /// Albion's "The Lost Stone" (20192-20195) asks for the player's name at Gavon Montgomery (the period guide: "When
    /// he asks, tell him your name"); its AdvanceText is <c>&lt;Player&gt;</c>.
    /// </summary>
    public static class QuestWhispers
    {
        /// <summary>True when <paramref name="whispered"/> advances a step whose AdvanceText is
        /// <paramref name="advanceText"/>; <paramref name="personalized"/> is that text as the player reads it
        /// (BehaviourUtils.GetPersonalizedMessage). The text itself matches exactly, as upstream compared it. When it
        /// holds a token the server replaced (<paramref name="personalized"/> differs), the text the player reads matches
        /// too, without case (ordinal): a name is typed as the player likes. A plain text, or one whose only token the
        /// server doesn't know, still needs the exact text.</summary>
        public static bool Advances(string advanceText, string personalized, string whispered)
            => advanceText == whispered
               || (personalized != advanceText && string.Equals(personalized, whispered, StringComparison.OrdinalIgnoreCase));
    }
}

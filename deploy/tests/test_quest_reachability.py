"""Every classic quest that starts on a keyword can be started from what its giver says (quest entry scan, 2026-10-11).

A quest with StartType 0 starts when the player whispers its AcceptText to the giver, exactly (DataQuest's
CheckOfferedQuestWhisper). The player does that by clicking a [keyword] the giver said: in the quest's Description
(shown when the player qualifies) or in another quest text the giver says. A clicked keyword gets ClassicQuests' Chat
reply for that NPC, which may offer more keywords. Upstream's generator lost lines and keys on the way, so seven quests
(35 rows) could not be started, and many texts said <Player> (the player's name, in game) where the period named
someone else, which left two more without a way in. It also wrote <Player> for plain words ("Aye, Well, it's") and
the player's class, kept spaces in keys that a click never sends, and filed Kylirean's lines under another name. It
also kept the class the guides' authors were called by ("Good luck to thee Theurgist.") and the guides' placeholders
("(class name)"), which every class read, and the web page it scraped after Mystemas's last line. The fixes are in
deploy/hearthdaoc-quests.json (Chat) and deploy/bin/quest_dialogue.json (world texts).

The world tests run world_fixes on a copy of a clean classic world (HDC_TEST_WORLD) and merge upstream's Chat with the
fork's as ClassicQuests.MergeChat does. Upstream's Chat is in its classic-quests.json, a server file the first start
downloads: HDC_CLASSIC_QUESTS names it, or the tests take the one init_world.py put in the data folder that holds
HDC_TEST_WORLD (as in CI).
"""
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(DEPLOY, "bin"))

import world_fixes as wf  # noqa: E402
from tests.test_quest_dialogue import GUIDE_PLACEHOLDERS, SCRAPED_WORDS  # noqa: E402

TEST_WORLD = os.environ.get("HDC_TEST_WORLD")
EXTRA_QUESTS = os.path.join(DEPLOY, "hearthdaoc-quests.json")
BRACKETS = re.compile(r"\[([^\[\]]+)\]")


def upstream_quests_file():
    """Upstream's classic-quests.json, or None. In a data folder init_world.py made, the file must be there."""
    if os.environ.get("HDC_CLASSIC_QUESTS"):
        return os.environ["HDC_CLASSIC_QUESTS"]
    if not TEST_WORLD:
        return None
    files = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(TEST_WORLD))), "server-files")
    if not os.path.isdir(files):
        return None
    with open(os.path.join(DEPLOY, "upstream.lock"), encoding="utf-8") as f:
        version = json.load(f)["version"]
    return os.path.join(files, version, "classic-quests.json")


UPSTREAM_QUESTS = upstream_quests_file()


def whisper_key(text):
    """What OnWhisper looks up: the text trimmed, and of trailing .!? (lookups ignore case)."""
    return text.strip().rstrip(".!?").lower()


def merged_chat(upstream, extra):
    """{npc: {keyword: reply}}, lowercased, as ClassicQuests.MergeChat builds it: upstream's keywords as they are, the
    fork's trimmed like a whisper and replacing upstream's."""
    chat = defaultdict(dict)
    for npc, lines in (upstream or {}).items():
        for keyword, reply in (lines or {}).items():
            chat[npc.lower()][keyword.lower()] = reply
    for npc, lines in (extra or {}).items():
        for keyword, reply in (lines or {}).items():
            chat[npc.lower()][whisper_key(keyword or "")] = reply or ""
    return chat


def extra_chat():
    with open(EXTRA_QUESTS, encoding="utf-8") as f:
        return json.load(f).get("Chat") or {}


def merge_quests(upstream, extra):
    """{quest ID: entry}: upstream's "Quests" with the fork file's, as ClassicQuests.Merge merges them. Our entry with
    "Replace" replaces upstream's, and ours for an ID upstream lacks is added; for any other ID upstream's entry stays,
    with our "XpShares" and steps' "Greet" laid onto it (overlaid). IDs stay strings; our "_" notes and null entries are
    skipped. Neither input is changed."""
    quests = dict(upstream or {})
    for qid, info in (extra or {}).items():
        if qid.startswith("_") or info is None:
            continue
        if info.get("Replace") or qid not in quests:
            quests[qid] = info
        elif quests[qid] is not None:
            quests[qid] = overlaid(quests[qid], info)
    return quests


def overlaid(entry, ours):
    """A copy of upstream's entry with ours laid onto it, as ClassicQuestOverlay.Apply does: a non-empty "XpShares"
    replaces upstream's list; a step's "Greet" replaces upstream's greeting on that step ("" removes it), adding the
    step where upstream's list has none. Nothing else of ours counts."""
    entry = dict(entry)
    if ours.get("XpShares"):
        entry["XpShares"] = list(ours["XpShares"])
    greets = [(i, step["Greet"]) for i, step in enumerate(ours.get("Steps") or [])
              if step and step.get("Greet") is not None]
    if greets:
        steps = list(entry.get("Steps") or [])
        for i, greet in greets:
            if greet == "":
                if i < len(steps) and steps[i]:
                    steps[i] = {key: value for key, value in steps[i].items() if key != "Greet"}
            else:
                steps += [None] * (i + 1 - len(steps))
                steps[i] = {**(steps[i] or {}), "Greet": greet}
        entry["Steps"] = steps
    return entry


def said_by(conn):
    """{npc: [text]}: the quest texts each NPC says, lowercased names. A quest's giver says its Description; its
    SourceText and FinishText reach the player beside the giver or a target; a stage's target says that stage's
    TargetText."""
    said = defaultdict(list)
    for giver, targets, description, source, target_texts, finish in conn.execute(
            "SELECT StartName, TargetName, Description, SourceText, TargetText, FinishText FROM DataQuest"):
        giver = (giver or "").lower()
        names = [name.split(";")[0].lower() for name in (targets or "").split("|")]
        said[giver].append(description or "")
        for stage, text in enumerate((target_texts or "").split("|")):
            if stage < len(names) and names[stage]:
                said[names[stage]].append(text)
        for text in (source or "").split("|") + (finish or "").split("|"):
            for npc in {giver, *filter(None, names)}:
                said[npc].append(text)
    return said


def offered(texts, replies, quest=None):
    """Every keyword a player can click from `texts`, following the NPC's Chat `replies`, as /whisper sends it (its
    words joined with one space). A keyword that holds <Player> shows the player's own name (GetPersonalizedMessage),
    which no key matches. With `quest`, a reply keyed "keyword@<quest>" answers before the plain keyword's, as
    ClassicQuests.ChatReply answers a player who may take that quest."""
    seen, todo = set(), [keyword for text in texts for keyword in BRACKETS.findall(text)]
    while todo:
        keyword = todo.pop()
        if keyword in seen:
            continue
        seen.add(keyword)
        if "<player>" in keyword.lower():
            continue
        key = whisper_key(keyword)
        reply = replies.get(f"{key}@{quest}") if quest is not None else None
        reply = replies.get(key) if reply is None else reply
        if reply and reply.strip():
            todo.extend(BRACKETS.findall(reply))
    return {" ".join(keyword.split()) for keyword in seen}


def unanswered(texts, replies):
    """The keywords a player can click from `texts` that get no Chat reply."""
    return sorted(keyword for keyword in offered(texts, replies)
                  if not (replies.get(whisper_key(keyword)) or "").strip())


# The fork's replies that replace an upstream reply holding <Player> and still speak to the player, and how many
# <Player> each keeps: Skorri's "Please <Player>, give Olvaerr his cloak", Thorgil's "You cannot use a bow,
# <Player>." (the guide's "Spiritmaster": a class as a title, which the fork leaves as <Player>) and Grindan Halig's
# "Best of luck <Player>!" (the fork changes only his class word), and Tethra's "Thank you, <Player>." and "Good day
# to you, <Player>" (the fork cuts only the editor's "(sic)").
SPEAKS_TO_THE_PLAYER = {("skorri", "a cloak"): 1, ("thorgil", "staff"): 1,
                        ("grindan halig", "willing to bear the weight"): 1, ("tethra", "no more heads"): 2}

# The class the guides' authors were called by, which upstream's Chat kept as plain text, so every class read the
# author's (class-word scan, 2026-10-11). The fork's reply is upstream's with these words alone changed: the class, and
# the guides' placeholders "(minstrel)" and "(class name)", become <Class>, which the server replaces with the player's
# class (GetPersonalizedMessage; female names included). {(NPC, the fork's key, upstream's key): [(upstream's words, the
# fork's)]}. Upstream's key for Gral Bermorn's reply keeps the guide's spaces, which no whisper sends: players get his
# fork key's reply, which was upstream's word for word. Siv Alfevson's "Spiritmaster" came with the later lines of his
# conversation that 0.37 gave his [our clan] (0.37 sync, #138).
CHAT_CLASS_WORDS = {
    ("gral bermorn", "opened from the other side", " opened from the other side "): [
        ("take these instructions to aid you. Good luck to thee Theurgist.",
         "take these instructions to aid you. Good luck to thee <Class>.")],
    ("broc", "slay a few", "slay a few"): [
        ("I will consider this proof of your deeds. Safe travels Enchanter.",
         "I will consider this proof of your deeds. Safe travels <Class>.")],
    ("mystemas", "understand", "understand"): [
        ("Bring me Caisha like a good little (minstrel)", "Bring me Caisha like a good little <Class>")],
    ("iohannes aldar", "pay generously", "pay generously"): [
        ("This is great (class name)!", "This is great <Class>!"), ("Good luck (class name)!", "Good luck <Class>!")],
    ("grindan halig", "willing to bear the weight", "willing to bear the weight"): [
        ("Ah! Very good (class name)!", "Ah! Very good <Class>!")],
    ("siv alfevson", "our clan", "our clan"): [
        ("I can assist you no more Spiritmaster.", "I can assist you no more <Class>.")],
}

# The guides' notes that came into upstream's Chat with the later lines of a recorded conversation (0.36 and 0.37; the
# 0.37 sync, #138): a walkthrough's note after Elizabeth's last line, and an editor's "(sic)" in Tethra's and Cristin's
# replies. The fork's reply is upstream's without them. {(NPC, keyword): (upstream's words, the fork's)}
CHAT_NOTES = {
    ("elizabeth", "other items"): ("you cannot change your mind. After turning in both items to Elizabeth, gain "
                                   "62,914,560 experience as well Two Handed Conclusion:", "you cannot change your mind."),
    ("tethra", "no more heads"): ("unusually villianous (sic), and", "unusually villianous, and"),
    ("cristin", "three things"): ("around Connacht (sic) . The first", "around Connacht . The first"),
}

# The lines upstream's generator had lost, which the fork's Chat gave back (quest entry scan, 2026-10-11) and upstream
# 0.37 restored, with the guides' typos fixed ("andhis", "stone" for "stole", "fromt he"): upstream's again.
RESTORED_UPSTREAM = [("hugh gallen", "bit of information"), ("sugnhild", "loved one"), ("sugnhild", "gudlor"),
                     ("sugnhild", "searched many weeks"), ("achae smith", "out here"), ("vadri pade", "druid tale")]


# The web page upstream scraped with Mystemas's last line (Strange Bedfellows): the guide's reward, then the site's
# footer, "... (c) 2026 Fanbyte LLC". The fork's reply ends where the guide's line does, without a stop.
SCRAPED_FROM = {("mystemas", "understand"): " Reward: Perfect Life Stone Free account required to post "}


def not_the_npcs_words(chat):
    """[(npc, keyword, words)]: the replies of `chat` that hold a guide's placeholder or a web page's words."""
    return [(npc, key, words) for npc, lines in chat.items() for key, reply in lines.items()
            for words in GUIDE_PLACEHOLDERS + SCRAPED_WORDS if words.lower() in (reply or "").lower()]


def with_class_words(text, words):
    """`text` with each (upstream's words, the fork's) pair of `words` replaced; upstream's words are there once."""
    for old, new in words:
        if text.count(old) != 1:
            raise AssertionError(f"{old!r} is in the text {text.count(old)} times, not once")
        text = text.replace(old, new)
    return text


class PeriodChatTests(unittest.TestCase):
    """The fork's Chat lines for the classic quests."""

    def setUp(self):
        self.chat = merged_chat({}, extra_chat())

    def test_kaere_answers_her_question_without_its_question_mark(self):
        # Upstream's key ends in "?", which OnWhisper trims from the click: [Will you gather ...] got no reply.
        # [get it for me] was the period's accept click; it gets the same reply.
        kaere = self.chat["kaere"]
        reply = kaere["will you gather the components for keare's spell to protect anniogel"]
        self.assertIn("[can be found]", reply)
        self.assertEqual(kaere["get it for me"], reply)

    @unittest.skipUnless(UPSTREAM_QUESTS, "needs upstream's classic-quests.json (HDC_CLASSIC_QUESTS)")
    def test_the_lines_upstream_restored_are_upstreams(self):
        with open(UPSTREAM_QUESTS, encoding="utf-8") as f:
            upstream = merged_chat(json.load(f).get("Chat"), {})
        for npc, keyword in RESTORED_UPSTREAM:
            with self.subTest(npc=npc, keyword=keyword):
                self.assertNotIn(keyword, self.chat.get(npc, {}))
                self.assertTrue(upstream[npc][keyword].strip())
        self.assertIn("his son, Durren, [was slain]", upstream["hugh gallen"]["bit of information"])
        self.assertIn("beset upon by this small sprite and his followers", upstream["sugnhild"]["searched many weeks"])
        self.assertIn("Then from the northern shores came", upstream["vadri pade"]["druid tale"])
        # Achae Smith's [another favor] stays the fork's: upstream's still asks for "<Player>'s remains".
        self.assertIn("Will you please find Thulin's remains for me?", self.chat["achae smith"]["another favor"])

    def test_the_guides_notes_are_cut_from_the_replies(self):
        for (npc, key), (old, new) in CHAT_NOTES.items():
            with self.subTest(npc=npc, keyword=key):
                self.assertEqual(self.chat[npc][key].count(new), 1)
                self.assertNotIn(old, self.chat[npc][key])
        self.assertTrue(self.chat["elizabeth"]["other items"].endswith(
            "Which do you desire - [one handed] or [two handed] or a [shield]. Choose carefully, for once your choice "
            "is made; you cannot change your mind."))
        self.assertNotIn("(sic)", self.chat["tethra"]["no more heads"] + self.chat["cristin"]["three things"])

    @unittest.skipUnless(UPSTREAM_QUESTS, "needs upstream's classic-quests.json (HDC_CLASSIC_QUESTS)")
    def test_the_replies_without_the_guides_notes_are_upstreams(self):
        with open(UPSTREAM_QUESTS, encoding="utf-8") as f:
            upstream = merged_chat(json.load(f).get("Chat"), {})
        for (npc, key), words in CHAT_NOTES.items():
            with self.subTest(npc=npc, keyword=key):
                self.assertEqual(self.chat[npc][key], with_class_words(upstream[npc][key], [words]))

    def test_the_keywords_that_were_player_are_names(self):
        # Upstream's keys "<Player>" (and Rollo's "retrieve the <Player> item") never match: the player clicks their
        # own name. The fixed replies offer the period's name, and the fork's Chat answers it.
        for npc, keyword in (("danica", "runil"), ("sentry dwarn", "morana"), ("atzar", "askheim"),
                             ("rollo", "retrieve the brack item")):
            with self.subTest(npc=npc, keyword=keyword):
                self.assertTrue(self.chat[npc][keyword].strip())
        for npc, lines in self.chat.items():
            for keyword in lines:
                self.assertNotIn("<player>", keyword, npc)

    def test_the_words_that_were_player_are_the_guides(self):
        # Upstream's generator took a plain word for a name: the guides have "Aye, Well, it's" and "Yes, Yes, I know".
        self.assertTrue(self.chat["crace"]["enchanted silver"].startswith("Aye, Well, it's mainly controlled by "))
        self.assertIn("the Path of Focus. Yes, Yes, I know you already spoke with her", self.chat["keriann"]["hamlet"])

    def test_a_class_said_as_a_noun_is_the_players_class(self):
        # The guides' authors played a Hunter ("this fine Hunter") and a Spiritmaster ("a Spiritmaster like you"). The
        # server replaces <Class> with the player's class (GetPersonalizedMessage), as it does <Player> with the name.
        self.assertEqual(self.chat["skorri"]["a cloak"],
                         "Look Olvaerr, this fine <Class> has found your cloak! Please <Player>, give Olvaerr his "
                         "cloak so that he will no longer think that Ailsa stole it from him. Perhaps he will even "
                         "apologize to Alisa.")
        self.assertEqual(self.chat["thorgil"]["staff"],
                         "You cannot use a bow, <Player>. Perhaps a <Class> like you would prefer a nice [staff]?")

    def test_the_class_the_guides_authors_were_called_by_is_the_players(self):
        # Gral Bermorn's "Good luck to thee Theurgist." (Weakened Bonds, open to every class), Broc's "Safe travels
        # Enchanter.", and the guides' placeholders: Mystemas's "(minstrel)", Iohannes Aldar's and Grindan Halig's
        # "(class name)".
        for (npc, key, _upstream_key), words in CHAT_CLASS_WORDS.items():
            for old, new in words:
                with self.subTest(npc=npc, keyword=key, words=new):
                    self.assertEqual(self.chat[npc][key].count(new), 1)
                    self.assertNotIn(old, self.chat[npc][key])
        self.assertEqual(self.chat["broc"]["slay a few"],
                         "Very well then! Return to me any [melancholic] fairy wings you may find. I will consider "
                         "this proof of your deeds. Safe travels <Class>.")
        self.assertEqual(self.chat["grindan halig"]["willing to bear the weight"],
                         "Ah! Very good <Class>! I think you will do nicely. I do not know how best to proceed I "
                         "suggest that you speak with Iohannes Aldar at Cornwall station. Perhaps if you listen to his "
                         "story and study the tomb well, you will find the key to [learning] the name of the emperor. "
                         "Best of luck <Player>!")

    def test_mystemas_s_last_line_ends_where_the_guide_s_does(self):
        self.assertEqual(self.chat["mystemas"]["understand"],
                         "Good. Now get going before someone sees us talking. Bring me Caisha like a good little <Class>")

    def test_no_fork_reply_holds_a_guides_placeholder_or_a_web_page(self):
        self.assertEqual(not_the_npcs_words(self.chat), [])

    @unittest.skipUnless(UPSTREAM_QUESTS, "needs upstream's classic-quests.json (HDC_CLASSIC_QUESTS)")
    def test_the_class_word_replies_are_upstreams_with_the_players_class(self):
        # Only the class words change, and Mystemas's reply ends before the page upstream scraped after it, which runs
        # to the reply's end.
        with open(UPSTREAM_QUESTS, encoding="utf-8") as f:
            upstream = merged_chat(json.load(f).get("Chat"), {})
        for (npc, key, upstream_key), words in CHAT_CLASS_WORDS.items():
            with self.subTest(npc=npc, keyword=key):
                reply = upstream[npc][upstream_key]
                if (npc, key) in SCRAPED_FROM:
                    reply, page = reply.split(SCRAPED_FROM[(npc, key)])
                    self.assertTrue(page.endswith(" Connect With Fanbyte \u00a9 2026 Fanbyte LLC"), page)
                self.assertEqual(self.chat[npc][key], with_class_words(reply, words))

    @unittest.skipUnless(UPSTREAM_QUESTS, "needs upstream's classic-quests.json (HDC_CLASSIC_QUESTS)")
    def test_no_reply_holds_a_guides_placeholder_or_a_web_page(self):
        # The guard, with upstream's Chat merged as MergeChat does, over every key, whether a whisper reaches it or not:
        # upstream's replies that hold one (Mystemas's [Understand], Iohannes Aldar's [pay generously], Grindan Halig's
        # [willing to bear the weight]) are all replaced by the fork's.
        with open(UPSTREAM_QUESTS, encoding="utf-8") as f:
            upstream = json.load(f).get("Chat")
        self.assertEqual(sorted({(npc, key) for npc, key, _words in not_the_npcs_words(merged_chat(upstream, {}))}),
                         [("grindan halig", "willing to bear the weight"), ("iohannes aldar", "pay generously"),
                          ("mystemas", "understand")])
        self.assertEqual(not_the_npcs_words(merged_chat(upstream, extra_chat())), [])

    @unittest.skipUnless(UPSTREAM_QUESTS, "needs upstream's classic-quests.json (HDC_CLASSIC_QUESTS)")
    def test_no_reply_a_whisper_reaches_says_a_class_word_the_fork_fixed(self):
        # The guard: with upstream's Chat merged as MergeChat does, no reply a player can get still has the guides'
        # class words (an NPC answers every class alike). A key OnWhisper can match is trimmed and has no trailing .!?;
        # upstream's " opened from the other side " is not one, so its copy of Gral Bermorn's reply reaches no one.
        with open(UPSTREAM_QUESTS, encoding="utf-8") as f:
            chat = merged_chat(json.load(f).get("Chat"), extra_chat())
        fixed = [old for words in CHAT_CLASS_WORDS.values() for old, _new in words]
        said = [(npc, key, old) for npc, lines in chat.items() for key, reply in lines.items() for old in fixed
                if key == whisper_key(key) and old in (reply or "")]
        self.assertEqual(said, [])
        self.assertIn("Theurgist.", chat["gral bermorn"][" opened from the other side "])
        self.assertNotEqual(whisper_key(" opened from the other side "), " opened from the other side ")

    def test_gral_bermorns_keywords_are_answered_without_their_spaces(self):
        # Upstream's keys kept the guide's spaces (" switch "); a click on [ switch ] whispers "switch".
        gral = self.chat["gral bermorn"]
        self.assertEqual(offered(["[ switch ]"], gral), {"switch", "axis circle", "opened from the other side"})
        self.assertEqual(unanswered(["[ switch ]"], gral), [])
        self.assertTrue(gral["opened from the other side"].startswith("You must be ready for Glasan at this point."))

    def test_nibalk_answers_ibicus(self):
        # The guide: Nibalk asks "Are you hunting [Ibicus]?" and answers it; upstream's key was <Player>.
        self.assertEqual(offered(["[Ibicus]"], self.chat["nibalk"]), {"Ibicus", "Mussalkan"})
        self.assertTrue(self.chat["nibalk"]["ibicus"].startswith("Yes, that large sea beast"))

    def test_kylirean_has_his_lines_under_the_spawns_name(self):
        # Upstream filed them under "Kyrilean", the guide author's spelling; Mythic's (patch notes, the Prima guide)
        # and the world's is Kylirean, and ClassicQuests finds an NPC's lines by its name.
        kylirean = self.chat["kylirean"]
        self.assertEqual(offered(["[experiment]"], kylirean), {"experiment", "down", "hide", "help me out"})
        self.assertEqual(unanswered(["[experiment]", "[item]"], kylirean), [])

    @unittest.skipUnless(UPSTREAM_QUESTS, "needs upstream's classic-quests.json (HDC_CLASSIC_QUESTS)")
    def test_no_reply_the_fork_fixed_still_says_player(self):
        # Every fork reply that replaces an upstream reply holding <Player> names the period's person or word instead,
        # but where it still speaks to the player.
        with open(UPSTREAM_QUESTS, encoding="utf-8") as f:
            upstream = merged_chat(json.load(f).get("Chat"), {})
        fixed = 0
        for npc, lines in self.chat.items():
            for keyword, reply in lines.items():
                if "<Player>" in upstream.get(npc, {}).get(keyword, ""):
                    fixed += 1
                    with self.subTest(npc=npc, keyword=keyword):
                        self.assertEqual(reply.count("<Player>"), SPEAKS_TO_THE_PLAYER.get((npc, keyword), 0))
        self.assertGreater(fixed, 0)

    @unittest.skipUnless(UPSTREAM_QUESTS, "needs upstream's classic-quests.json (HDC_CLASSIC_QUESTS)")
    def test_the_moved_replies_are_upstreams(self):
        # Gral Bermorn's trimmed keys, Nibalk's [Ibicus] and Kylirean's lines carry upstream's replies as they are, but
        # for the class words (CHAT_CLASS_WORDS: Gral Bermorn's "Theurgist").
        with open(UPSTREAM_QUESTS, encoding="utf-8") as f:
            upstream = merged_chat(json.load(f).get("Chat"), {})
        moved = [("gral bermorn", " switch ", "gral bermorn", "switch"),
                 ("gral bermorn", " axis circle ", "gral bermorn", "axis circle"),
                 ("gral bermorn", " opened from the other side ", "gral bermorn", "opened from the other side"),
                 ("nibalk", "<player>", "nibalk", "ibicus")]
        moved += [("kyrilean", keyword, "kylirean", keyword) for keyword in upstream["kyrilean"]]
        self.assertEqual(len(moved), 9)
        for npc, key, ours, our_key in moved:
            with self.subTest(npc=ours, keyword=our_key):
                words = CHAT_CLASS_WORDS.get((ours, our_key, key), [])
                self.assertEqual(self.chat[ours][our_key], with_class_words(upstream[npc][key], words))


@unittest.skipUnless(TEST_WORLD and UPSTREAM_QUESTS, "needs HDC_TEST_WORLD (a clean classic world database) and "
                                                     "upstream's classic-quests.json (HDC_CLASSIC_QUESTS)")
class ReachabilityTests(unittest.TestCase):
    """The world data after the world fixes, and upstream's Chat merged with the fork's."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = os.path.join(cls.tmp.name, "world.db")
        shutil.copyfile(TEST_WORLD, cls.db)
        wf.apply(cls.db)
        cls.conn = sqlite3.connect(cls.db)
        with open(UPSTREAM_QUESTS, encoding="utf-8") as f:
            cls.chat = merged_chat(json.load(f).get("Chat"), extra_chat())
        cls.said = said_by(cls.conn)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_every_keyword_quest_can_be_started_from_what_its_giver_says(self):
        unreachable = []
        for qid, name, giver, accept in self.conn.execute(
                "SELECT ID, Name, StartName, AcceptText FROM DataQuest WHERE StartType=0 ORDER BY ID"):
            npc = (giver or "").lower()
            if accept not in offered(self.said[npc], self.chat.get(npc, {}), qid):
                unreachable.append(f"{qid} {name} ({giver}: [{accept}])")
        self.assertEqual(unreachable, [], f"{len(unreachable)} quest rows can't be started")

    def test_hugh_gallen_offers_his_bit_of_information_and_names_durren(self):
        # The owner's report (level 5 "Cleric Mulgrut", 2026-10-11): Hugh Gallen only offered his wares.
        description, = self.conn.execute("SELECT Description FROM DataQuest WHERE ID=20207").fetchone()
        self.assertIn("[bit of information]", description)
        self.assertIn("bit of information", offered([description], self.chat["hugh gallen"]))
        self.assertIn("his son, Durren, [was slain]", self.chat["hugh gallen"]["bit of information"])

    def test_the_names_that_were_player_are_offered(self):
        for npc, keyword in (("danica", "Runil"), ("sentry dwarn", "Morana"), ("atzar", "Askheim"),
                             ("rollo", "retrieve the Brack item")):
            with self.subTest(npc=npc, keyword=keyword):
                self.assertIn(keyword, offered(self.said[npc], self.chat[npc]))

    def stage(self, qid, column, stage):
        text, = self.conn.execute(f"SELECT {column} FROM DataQuest WHERE ID=?", (qid,)).fetchone()
        return (text or "").split("|")[stage - 1]

    def test_the_fixed_replies_are_offered_where_the_quests_show_them(self):
        # Crace's [enchanted silver] (Silver Run, stage 1), Skorri's [a cloak] (Solving the Argument, sent on accept)
        # and Gral Bermorn's three (Weakened Bonds, stages 2 and 13, said by him; every keyword there is answered).
        shown = [(20288, "TargetText", 1, "crace", "enchanted silver"), (21142, "SourceText", 1, "skorri", "a cloak"),
                 (20639, "TargetText", 2, "gral bermorn", "opened from the other side"),
                 (20639, "TargetText", 13, "gral bermorn", "opened from the other side")]
        for qid, column, stage, npc, keyword in shown:
            with self.subTest(quest=qid, stage=stage, keyword=keyword):
                text = self.stage(qid, column, stage)
                self.assertIn(keyword, offered([text], self.chat[npc]))
                self.assertEqual(unanswered([text], self.chat[npc]), [])

    def test_the_class_word_replies_are_offered_where_players_get_them(self):
        # Mystemas, Iohannes Aldar and Grindan Halig offer theirs from what they say in their quests' texts (Strange
        # Bedfellows, Fall of an Emperor), Gral Bermorn his from Weakened Bonds' [ switch ]. Broc's [have a moment],
        # which leads to his, is in no quest text: a player whispers it.
        for npc, key in (("mystemas", "Understand"), ("iohannes aldar", "pay generously"),
                         ("grindan halig", "willing to bear the weight"),
                         ("gral bermorn", "opened from the other side")):
            with self.subTest(npc=npc):
                self.assertIn(key, offered(self.said[npc], self.chat[npc]))
                self.assertIn("<Class>", self.chat[npc][whisper_key(key)])
        self.assertIn("slay a few", offered(["[have a moment]"], self.chat["broc"]))

    def test_new_crest_is_offered_under_each_trainers_own_class(self):
        # The guide's author was a Bonedancer, and upstream's Runemaster and Spiritmaster rows asked for [Bonedancer]
        # too. DataQuest compares the accept keyword as it is (no <Class>), so each row's is its own class.
        for qid, giver, accept, allowed in ((20349, "Etta Greavers", "Runemaster", "29"),
                                            (20350, "Palda", "Spiritmaster", "27"),
                                            (20351, "Teija", "Bonedancer", "30")):
            with self.subTest(quest=qid):
                row = self.conn.execute("SELECT StartName, AcceptText, AllowedClasses, Description FROM DataQuest "
                                        "WHERE ID=?", (qid,)).fetchone()
                self.assertEqual(row[:3], (giver, accept, allowed))
                self.assertTrue(row[3].startswith(f"Ah, [{accept}]. You've aided Karle before, haven't you?"), row[3])
                self.assertIn(accept, offered(self.said[giver.lower()], self.chat.get(giver.lower(), {})))

    def test_the_words_that_were_player_in_quest_texts_are_the_guides(self):
        # Upstream's generator took "Now" and "Well" for names. Silver Run's Crace keeps <Player> where he speaks to the
        # player ("Well, Elline, did you get the sporites?", "I hope you find it useful, Warden!").
        description, = self.conn.execute("SELECT Description FROM DataQuest WHERE ID=20013").fetchone()
        self.assertIn("hiding from Arawn for years, Now, with the Inconnu walking the land", description)
        for qid in (20288, 20289, 20290, 20291):
            for stage in (1, 5):
                with self.subTest(quest=qid, stage=stage):
                    text = self.stage(qid, "TargetText", stage)
                    for words in ("are you? Well, you know about the [enchanted silver]", "Aye, Well, it's mainly",
                                  "two sporites. Well, <Player>, did you get", "quite useful. Well, that's what",
                                  "I hope you find it useful, <Player>!"):
                        self.assertIn(words, text)
                    self.assertEqual(text.count("<Player>"), 2)
                    self.assertEqual(unanswered([text], self.chat["crace"]), [])

    def test_wariel_and_amora_ask_the_players_name_and_answer_it(self):
        # The period's keyword was [name]; upstream's generator wrote <Player>: "What is your <the player's name>?". The
        # fork's Chat answers [name] with the guides' next line, as upstream's answers the texts' other keywords.
        asks = [(20099, 1, "wariel", "Well hello young one. What is your [name]? Well, it is a pleasure"),
                (20099, 7, "wariel", "Well hello young one. What is your [name]? Well, it is a pleasure")]
        asks += [(qid, 1, "amora", "Hello stranger, may I ask your [name]? It is a pleasure")
                 for qid in range(21102, 21118)]
        for qid, stage, npc, words in asks:
            with self.subTest(quest=qid, stage=stage):
                text = self.stage(qid, "TargetText", stage)
                self.assertIn(words, text)
                self.assertNotIn("<Player>", text)
                self.assertIn("name", offered([text], self.chat[npc]))
                self.assertEqual(unanswered([text], self.chat[npc]), [])
        self.assertTrue(self.chat["wariel"]["name"].startswith("Well, it is a pleasure to meet you."))
        self.assertTrue(self.chat["amora"]["name"].startswith("It is a pleasure to meet you."))

    def test_every_npc_the_forks_chat_names_stands_in_the_world(self):
        # ClassicQuests finds an NPC's lines by its name (without case): upstream's "Kyrilean" reached no one.
        names = {name.lower() for (name,) in self.conn.execute("SELECT Name FROM Mob")}
        self.assertEqual([npc for npc in extra_chat() if npc.lower() not in names], [])
        giver, = self.conn.execute("SELECT StartName FROM DataQuest WHERE ID=20068").fetchone()
        self.assertEqual(giver, "Kylirean")
        self.assertIn("experiment", self.chat[giver.lower()])


class QuestMergeTests(unittest.TestCase):
    """merge_quests mirrors ClassicQuests.Merge for the quest entries (Tests/UnitTests/UT_ClassicQuestsExtra.cs): the
    world tests that read both files see the merged entries the server uses."""

    UPSTREAM = {"20433": {"XpShares": [0.0, 0.0, 0.100364],
                          "Steps": [None, {"Marker": {"Region": 1, "X": 1, "Y": 2, "Z": 3}, "Greet": "Back already?"},
                                    {"Greet": "Were you able to deliver the dispatch?"},
                                    {"Greet": "Did Twr ap Alsig take the dispatch?"}]}}

    def merged(self, extra, upstream=None):
        return merge_quests(json.loads(json.dumps(upstream or self.UPSTREAM)), extra)

    def test_our_xp_shares_win_on_upstreams_entry(self):
        quest = self.merged({"20433": {"XpShares": [0.0, 0.0, 0.1]}})["20433"]
        self.assertEqual(quest["XpShares"], [0.0, 0.0, 0.1])
        self.assertEqual(quest["Steps"][1]["Marker"], {"Region": 1, "X": 1, "Y": 2, "Z": 3})
        self.assertEqual(quest["Steps"][2]["Greet"], "Were you able to deliver the dispatch?")

    def test_without_shares_of_ours_upstreams_stay(self):
        for ours in ({"Steps": [None]}, {"XpShares": [], "Steps": [None]}, {"XpShares": None, "Steps": [None]}):
            with self.subTest(ours=ours):
                self.assertEqual(self.merged({"20433": ours})["20433"]["XpShares"], [0.0, 0.0, 0.100364])

    def test_our_greet_wins_on_its_step_and_the_others_stay(self):
        sack = "Were you able to retrieve Tepok's precious sack?"
        steps = self.merged({"20433": {"Steps": [None, None, {"Greet": sack}]}})["20433"]["Steps"]
        self.assertEqual([step.get("Greet") for step in steps[1:]],
                         ["Back already?", sack, "Did Twr ap Alsig take the dispatch?"])

    def test_an_empty_greet_removes_upstreams(self):
        steps = self.merged({"20433": {"Steps": [None, None, {"Greet": ""}]}})["20433"]["Steps"]
        self.assertEqual([step.get("Greet") for step in steps[1:]],
                         ["Back already?", None, "Did Twr ap Alsig take the dispatch?"])

    def test_only_the_greet_of_our_step_is_carried(self):
        steps = self.merged({"20433": {"Steps": [None, {"Marker": {"Region": 1, "X": 9, "Y": 9, "Z": 9},
                                                        "NeedsItem": "cq_x"}]}})["20433"]["Steps"]
        self.assertEqual(steps[1], {"Marker": {"Region": 1, "X": 1, "Y": 2, "Z": 3}, "Greet": "Back already?"})
        self.assertEqual(len(steps), 4)

    def test_a_greet_on_a_step_upstream_has_no_info_for_adds_the_step(self):
        steps = self.merged({"20433": {"Steps": [None, {"Greet": "Back already?"}, None, {"Greet": "Well?"}]}},
                            {"20433": {"Steps": [None, None]}})["20433"]["Steps"]
        self.assertEqual(steps, [None, {"Greet": "Back already?"}, None, {"Greet": "Well?"}])

    def test_an_empty_greet_on_a_step_upstream_has_no_info_for_adds_nothing(self):
        quest = self.merged({"20433": {"Steps": [None, {"Greet": ""}, None, {"Greet": ""}]}},
                            {"20433": {"Steps": [None, None]}})
        self.assertEqual(quest["20433"]["Steps"], [None, None])

    def test_a_new_id_is_added_whole(self):
        ours = {"XpShares": [0.0, 0.1],
                "Steps": [None, {"Greet": "You return.", "Marker": {"Region": 1, "X": 5, "Y": 5, "Z": 5}}]}
        merged = self.merged({"990509": ours})
        self.assertEqual(sorted(merged), ["20433", "990509"])
        self.assertEqual(merged["990509"], ours)
        self.assertEqual(merged["20433"], self.UPSTREAM["20433"])

    def test_a_replace_entry_still_replaces_the_whole_entry(self):
        for ours in ({"Replace": True, "Steps": [None, {"Marker": {"Region": 1, "X": 9, "Y": 9, "Z": 9}}]},
                     {"Replace": True, "XpShares": [0.0, 0.25], "Steps": [None, {"Greet": "Mine."}]}):
            with self.subTest(ours=ours):
                self.assertEqual(self.merged({"20433": ours})["20433"], ours)

    def test_notes_and_null_entries_of_ours_are_skipped(self):
        self.assertEqual(self.merged({"_about": "notes", "20433": None, "990509": None}), self.UPSTREAM)

    def test_the_inputs_are_not_changed(self):
        upstream = json.loads(json.dumps(self.UPSTREAM))
        ours = {"20433": {"XpShares": [0.5], "Steps": [None, {"Greet": ""}, {"Greet": "Mine."}]}}
        before = json.dumps(ours)
        merge_quests(upstream, ours)
        self.assertEqual(upstream, self.UPSTREAM)
        self.assertEqual(json.dumps(ours), before)


if __name__ == "__main__":
    unittest.main()

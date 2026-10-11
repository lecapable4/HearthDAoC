"""Every classic quest that starts on a keyword can be started from what its giver says (quest entry scan, 2026-10-11).

A quest with StartType 0 starts when the player whispers its AcceptText to the giver, exactly (DataQuest's
CheckOfferedQuestWhisper). The player does that by clicking a [keyword] the giver said: in the quest's Description
(shown when the player qualifies) or in another quest text the giver says. A clicked keyword gets ClassicQuests' Chat
reply for that NPC, which may offer more keywords. Upstream's generator lost lines and keys on the way, so seven quests
(35 rows) could not be started, and many texts said <Player> (the player's name, in game) where the period named
someone else, which left two more without a way in. The fixes are in deploy/hearthdaoc-quests.json (Chat) and
deploy/bin/quest_dialogue.json (world texts).

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


def offered(texts, replies):
    """Every keyword a player can click from `texts`, following the NPC's Chat `replies`, as /whisper sends it (its
    words joined with one space). A keyword that holds <Player> shows the player's own name (GetPersonalizedMessage),
    which no key matches."""
    seen, todo = set(), [keyword for text in texts for keyword in BRACKETS.findall(text)]
    while todo:
        keyword = todo.pop()
        if keyword in seen:
            continue
        seen.add(keyword)
        if "<player>" in keyword.lower():
            continue
        reply = replies.get(whisper_key(keyword))
        if reply and reply.strip():
            todo.extend(BRACKETS.findall(reply))
    return {" ".join(keyword.split()) for keyword in seen}


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

    def test_hugh_gallen_names_durren(self):
        self.assertIn("his son, Durren, [was slain]", self.chat["hugh gallen"]["bit of information"])

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

    @unittest.skipUnless(UPSTREAM_QUESTS, "needs upstream's classic-quests.json (HDC_CLASSIC_QUESTS)")
    def test_no_reply_the_fork_fixed_still_says_player(self):
        # Every fork reply that replaces an upstream reply holding <Player> names the period's person instead.
        with open(UPSTREAM_QUESTS, encoding="utf-8") as f:
            upstream = merged_chat(json.load(f).get("Chat"), {})
        fixed = 0
        for npc, lines in self.chat.items():
            for keyword, reply in lines.items():
                if "<Player>" in upstream.get(npc, {}).get(keyword, ""):
                    fixed += 1
                    with self.subTest(npc=npc, keyword=keyword):
                        self.assertNotIn("<Player>", reply)
        self.assertGreater(fixed, 0)



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
            if accept not in offered(self.said[npc], self.chat.get(npc, {})):
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


if __name__ == "__main__":
    unittest.main()

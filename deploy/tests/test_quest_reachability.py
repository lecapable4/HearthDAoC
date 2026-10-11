"""The classic quests' period lines in the fork's Chat (quest entry scan, 2026-10-11).

A clicked [keyword] gets ClassicQuests' Chat reply for that NPC, which may offer more keywords. Upstream's generator
lost lines and keys on the way, so some quests could not be started, and many replies said <Player> (the player's
name, in game) where the period named someone else. deploy/hearthdaoc-quests.json gives the period's lines and names.

Upstream's Chat is in its classic-quests.json, a server file the first start downloads: HDC_CLASSIC_QUESTS names it, or
the tests take the one init_world.py put in the data folder that holds HDC_TEST_WORLD (as in CI).
"""
import json
import os
import unittest
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.dirname(HERE)

TEST_WORLD = os.environ.get("HDC_TEST_WORLD")
EXTRA_QUESTS = os.path.join(DEPLOY, "hearthdaoc-quests.json")


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


if __name__ == "__main__":
    unittest.main()

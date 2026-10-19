"""The line-ending check of the upstream files the fork edits (tests/endings.py; the 0.37 sync's review, finding
code-2).

Upstream ships some files with both endings, and "one ending per file" failed on them; it also passed a fork line
written in the file's other ending at a boundary, and nothing checked ClassicQuests.cs, upstream's file of 14 CRLF
lines in an LF file that the fork edits. endings.problems() compares a file with upstream's own version of it.
"""
import os
import unittest

from tests import endings

ROOT = endings.ROOT
CLASSIC_QUESTS = "source/server/GameServer/quests/QuestsMgr/ClassicQuests.cs"
GAME_PLAYER = "source/server/GameServer/gameobjects/GamePlayer.cs"
GAME_LIVING = "source/server/GameServer/gameobjects/GameLiving.cs"
# Upstream's file of both endings: an LF file with a CRLF block (ClassicQuests.cs's ScaleXP), and the fork's hook.
UPSTREAM = b"a\nb\nc\r\nd\r\ne\nf\n"
HOOK = b"    // HearthDAoC: a hook\n    hook();\n"


def blob(rev, rel):
    return endings.git_show(rev, rel)


def read(rel):
    with open(os.path.join(ROOT, rel), "rb") as f:
        return f.read()


def flip(raw, to):
    """raw with every line end made `to` (b"\\r\\n" or b"\\n"): a whole-file normalisation."""
    return raw.replace(b"\r\n", b"\n").replace(b"\n", to)


class ProblemsTests(unittest.TestCase):
    def test_upstreams_own_file_of_both_endings_passes(self):
        self.assertEqual(endings.problems(UPSTREAM, UPSTREAM), [])

    def test_a_fork_line_takes_the_ending_of_the_upstream_line_above_or_below(self):
        for ours in (UPSTREAM.replace(b"a\n", b"a\n" + HOOK),  # in the LF part
                     UPSTREAM.replace(b"c\r\n", b"c\r\n" + HOOK.replace(b"\n", b"\r\n")),  # in the CRLF part
                     UPSTREAM.replace(b"b\n", b"b\n" + HOOK),  # LF above, CRLF below: either
                     UPSTREAM.replace(b"b\n", b"b\n" + HOOK.replace(b"\n", b"\r\n"))):
            with self.subTest(ours=ours):
                self.assertEqual(endings.problems(ours, UPSTREAM), [])

    def test_a_fork_line_in_the_other_ending_fails(self):
        ours = UPSTREAM.replace(b"a\n", b"a\n" + HOOK.replace(b"hook();\n", b"hook();\r\n"))
        self.assertEqual(endings.problems(ours, UPSTREAM),
                         ["line 3 (a fork line) ends CRLF, the upstream lines beside it LF"])

    def test_an_upstream_line_that_changed_its_ending_fails(self):
        self.assertEqual(endings.problems(UPSTREAM.replace(b"d\r\n", b"d\n"), UPSTREAM),
                         ["line 4 ends LF, upstream's CRLF"])

    def test_a_whole_file_normalised_fails(self):
        self.assertEqual(endings.problems(flip(UPSTREAM, b"\n"), UPSTREAM),
                         ["line 3 ends LF, upstream's CRLF", "line 4 ends LF, upstream's CRLF"])
        self.assertEqual(len(endings.problems(flip(UPSTREAM, b"\r\n"), UPSTREAM)), 4)

    def test_a_lone_cr_and_a_bom_upstream_lacks_fail(self):
        self.assertEqual(endings.problems(b"a\rb\n", b"a\rb\n"), ["line 1 has a lone CR"])
        self.assertEqual(endings.problems(endings.BOM + UPSTREAM, UPSTREAM), ["the file has a BOM and upstream's has none"])
        self.assertEqual(endings.problems(UPSTREAM, endings.BOM + UPSTREAM), ["the file lacks upstream's BOM"])

    def test_without_upstreams_file_the_fork_lines_are_the_marked_blocks_and_the_rest_the_majority(self):
        lf = b"a\n" + HOOK + b"\nb\n"
        self.assertEqual(endings.problems(lf), [])
        self.assertEqual(endings.problems(lf.replace(b"hook();\n", b"hook();\r\n")),
                         ["line 3 (a fork line) ends CRLF, the upstream lines beside it LF"])
        self.assertEqual(endings.problems(lf.replace(b"b\n", b"b\r\n")),
                         [f"line 5 ends CRLF, the file's majority LF ({endings.NO_UPSTREAM})"])


@unittest.skipUnless(endings.upstream_rev(), "needs upstream's tag or commit of deploy/upstream.lock in this repository")
class UpstreamFilesTests(unittest.TestCase):
    """The check on upstream's real files of both endings, and on ClassicQuests.cs, which the fork edits."""

    def test_upstreams_files_of_both_endings_pass(self):
        # One ending per file failed on each: v0.36b's GamePlayer.cs (103 LF lines among CRLF ones), v0.37b's
        # GameLiving.cs and ClassicQuests.cs.
        for rev, rel in (("v0.36b", GAME_PLAYER), (endings.upstream_rev(), GAME_LIVING),
                         (endings.upstream_rev(), CLASSIC_QUESTS)):
            raw = blob(rev, rel)
            if raw is None:
                continue  # v0.36b's tag is not in every clone
            with self.subTest(rev=rev, file=rel):
                self.assertIn(b"\r\n", raw)
                self.assertNotEqual(raw.count(b"\r\n"), raw.count(b"\n"))
                self.assertEqual(endings.problems(raw, raw), [])

    def test_classic_quests_with_the_forks_hooks_passes(self):
        raw = read(CLASSIC_QUESTS)
        self.assertGreater(raw.count(b"HearthDAoC:"), 0)
        self.assertEqual(endings.problems(raw, endings.upstream_blob(CLASSIC_QUESTS)), [])

    def test_a_fork_line_of_classic_quests_in_the_other_ending_fails(self):
        raw = read(CLASSIC_QUESTS)
        hook = (b"if (QuestGrants.HandOnce(player, quest, id, step.GrantFrom)) continue; "
                b"// HearthDAoC: a real item once (QuestGrants)\n")
        self.assertEqual(raw.count(hook), 1)
        found = endings.problems(raw.replace(hook, hook[:-1] + b"\r\n"), endings.upstream_blob(CLASSIC_QUESTS))
        self.assertEqual(len(found), 1, found)
        self.assertRegex(found[0], r"^line \d+ \(a fork line\) ends CRLF, the upstream lines beside it LF$")

    def test_classic_quests_normalised_fails(self):
        # All LF: upstream's 14 CRLF lines (ScaleXP) are wrong; all CRLF: every LF line, upstream's and the fork's.
        raw, upstream = read(CLASSIC_QUESTS), endings.upstream_blob(CLASSIC_QUESTS)
        self.assertEqual(raw.count(b"\r\n"), 14)
        found = endings.problems(flip(raw, b"\n"), upstream)
        self.assertEqual(len(found), 14, found)
        self.assertTrue(all(line.endswith("ends LF, upstream's CRLF") for line in found), found)
        self.assertEqual(len(endings.problems(flip(raw, b"\r\n"), upstream)), raw.count(b"\n") - 14)


if __name__ == "__main__":
    unittest.main()

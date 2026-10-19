"""The start-log lines CI's container tests wait for are the lines the world fixes print on CI's test world.

deploy/tests/smoke.sh and deploy/tests/hdc_integration.sh run the image (CI's "Smoke test" and "Compose and hdc
integration test" steps): its first start builds the clean world of deploy/upstream.lock, as the "Build a clean classic
world for tests" step builds HDC_TEST_WORLD, and runs deploy/bin/world_fixes.py on it. They check some of its lines
word for word ("Quest dialogue: N quests rewritten"), which a world-fix change or a new upstream world changes, and no
deploy test ran them. This test runs the world fixes on a copy of HDC_TEST_WORLD and finds each line they expect:
smoke.sh's logs_have "..." in some line, its world-fixes.log list at the start of one, and hdc_integration.sh's
"^...$" as a whole line. Only lines of the world fixes are checked (the part before the first ":" is one of theirs).
"""
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))

import world_fixes  # noqa: E402

TEST_WORLD = os.environ.get("HDC_TEST_WORLD")
SMOKE = os.path.join(HERE, "smoke.sh")
HDC_IT = os.path.join(HERE, "hdc_integration.sh")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def expected():
    """(kind, line) for each world-fix line the container tests look for: "in" (somewhere in a line), "start" (at
    the start of one) or "whole" (the whole line)."""
    smoke, hdc = read(SMOKE), read(HDC_IT)
    out = [("in", s) for s in re.findall(r'logs_have "([^"]+)"', smoke)]
    loop = re.search(r"for line in (.*?); do", smoke.replace("\\\n", " "), re.S)
    out += [("start", s) for s in re.findall(r'"([^"]*)"', loop.group(1))] if loop else []
    out += [("whole", s) for s in re.findall(r'grep -q "\^([^"$]+)\$"', hdc)]
    return out


@unittest.skipUnless(TEST_WORLD, "needs HDC_TEST_WORLD (a clean classic world database)")
class ContainerLinesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        db = os.path.join(tmp.name, "world.db")
        shutil.copyfile(TEST_WORLD, db)
        os.chmod(db, 0o644)
        try:
            cls.lines = world_fixes.apply(db)
        finally:
            tmp.cleanup()

    def test_the_container_tests_expect_the_lines_the_world_fixes_print(self):
        heads = {line.split(":", 1)[0] for line in self.lines if ":" in line}
        checked = [(kind, s) for kind, s in expected() if s.split(":", 1)[0] in heads]
        self.assertGreaterEqual(len(checked), 8)  # smoke.sh's two and its six, hdc_integration.sh's two
        for kind, s in checked:
            with self.subTest(kind=kind, line=s):
                found = {"in": lambda line: s in line, "start": lambda line: line.startswith(s),
                         "whole": lambda line: line == s}[kind]
                self.assertTrue(any(found(line) for line in self.lines),
                                [line[:80] for line in self.lines if line.startswith(s.split(":", 1)[0])])


if __name__ == "__main__":
    unittest.main()

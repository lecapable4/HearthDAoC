"""Gamebots come back worth realm points, stage 1 (spec docs/fork/specs/2026-10-13-rp-timer-waits-design.md).

The switch goes .env -> compose.yml -> entrypoint.sh -> server_properties.py -> the bot_rp_timer_wait server
property, default on at every step (hdc update appends the new .env.example line to an existing .env). The
decisions are unit-tested (UT_RpTimerWait, UT_RpTimerWaitScript); the six hooks in upstream files, the handlers'
registration and the upstream facts the waits mirror need a live server, so these check the source.
"""
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.dirname(HERE)
ROOT = os.path.dirname(DEPLOY)
BIN = os.path.join(DEPLOY, "bin")
sys.path.insert(0, BIN)

import server_properties as sp  # noqa: E402
from tests.test_server_properties import SCHEMA, row  # noqa: E402

GAME_SERVER = os.path.join(ROOT, "source", "server", "GameServer")
FORK = os.path.join(GAME_SERVER, "scripts", "hearthdaoc")
SCRIPT_CS = os.path.join(FORK, "RpTimerWaitScript.cs")
DECISIONS_CS = os.path.join(FORK, "RpTimerWait.cs")
CONTROLLER_CS = os.path.join(FORK, "RpTimerWaitController.cs")
BOTS = os.path.join(GAME_SERVER, "bots", "autonomous")
WBC = os.path.join(BOTS, "AutonomousWorldBotController.cs")
BG = os.path.join(BOTS, "AutonomousWorldBotController.Battleground.cs")
FT = os.path.join(BOTS, "AutonomousWorldBotController.FrontierThreat.cs")
GC = os.path.join(BOTS, "AutonomousBotGroupCoordinator.cs")
KEEP_TRAVEL = os.path.join(BOTS, "AutonomousWorldBotController.KeepTravel.cs")
SIEGE = os.path.join(BOTS, "AutonomousWorldBotController.Siege.cs")
ARPR = os.path.join(BOTS, "AutonomousBotRealmPointRewards.cs")


def read(name):
    with open(os.path.join(DEPLOY, name), encoding="utf-8") as f:
        return f.read()


def source(path):
    """A C# source file's text (upstream files may start with a BOM)."""
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        return f.read()


def between(text, start, end):
    """The text from the first start up to the first end after it."""
    body = text[text.index(start):]
    return body[:body.index(end)]


def marked(test, body, call):
    """The body calls the fork once, with a // HearthDAoC: comment on the line above the call."""
    test.assertEqual(body.count(call), 1, call)
    above = body[:body.index(call)].rsplit("\n", 2)[-2]
    test.assertIn("// HearthDAoC:", above, call)


def cs_files(top):
    """Every .cs file under top, sorted."""
    found = []
    for folder, _, names in os.walk(top):
        found.extend(os.path.join(folder, name) for name in names if name.endswith(".cs"))
    return sorted(found)


class SwitchValueTests(unittest.TestCase):
    def test_on_and_off_in_any_case_become_true_and_false(self):
        for spec, expected in (("on", "True"), ("ON", "True"), ("On", "True"),
                               ("off", "False"), ("OFF", "False"), ("oFf", "False")):
            with self.subTest(spec=spec):
                self.assertEqual(sp.bot_rp_timer_wait_value(spec), expected)

    def test_other_values_are_refused(self):
        for bad in ("", "yes", "no", "true", "false", "1", "0", "none", "onn", " on", "off "):
            with self.subTest(bad=bad), self.assertRaisesRegex(
                    sp.PropertyError, f"^HEARTHDAOC_BOT_RP_TIMER_WAIT must be on or off, got {re.escape(repr(bad))}$"):
                sp.bot_rp_timer_wait_value(bad)

    def test_the_property_matches_the_server_declaration(self):
        self.assertEqual((sp.RP_WAIT_KEY, sp.RP_WAIT_DEFAULT), ("bot_rp_timer_wait", "False"))
        self.assertNotIn('"', sp.RP_WAIT_DESCRIPTION)
        self.assertNotIn("\\", sp.RP_WAIT_DESCRIPTION)


class EntrypointTests(unittest.TestCase):
    """Runs the entrypoint's own server_properties.py command against a scratch world."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.tmp.name, "world"))
        self.db = os.path.join(self.tmp.name, "world", "opendaoc.sqlite3.db")
        with sqlite3.connect(self.db) as c:
            c.execute(SCHEMA)
        lines = read("entrypoint.sh").replace("\\\n", " ").splitlines()
        commands = [line for line in lines if line.startswith('python3 "$BIN/server_properties.py"')]
        self.assertEqual(len(commands), 1, "the entrypoint runs server_properties.py once")
        self.command = commands[0]

    def tearDown(self):
        self.tmp.cleanup()

    def run_entrypoint_line(self, **env):
        script = f"set -euo pipefail\nBIN={shlex.quote(BIN)}\nDATA={shlex.quote(self.tmp.name)}\n{self.command}\n"
        base = {k: v for k, v in os.environ.items() if not k.startswith("HEARTHDAOC_")}
        return subprocess.run(["bash", "-c", script], env={**base, **env}, capture_output=True, text=True)

    def test_passes_the_setting_with_default_on(self):
        self.assertIn('--bot-rp-timer-wait "${HEARTHDAOC_BOT_RP_TIMER_WAIT-on}"', self.command)
        r = self.run_entrypoint_line()
        self.assertEqual((r.returncode, r.stdout, r.stderr),
                         (0, "GM-only commands: /tele;/tc\nShrouded Isles start choice: on\nBot realm point timer wait: on\n", ""))
        self.assertEqual(row(self.db, sp.RP_WAIT_KEY), ("server", sp.RP_WAIT_DESCRIPTION, "False", "True"))

    def test_off_in_any_case_turns_it_off(self):
        self.run_entrypoint_line()
        r = self.run_entrypoint_line(HEARTHDAOC_BOT_RP_TIMER_WAIT="OFF")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "Bot realm point timer wait: off\n", ""))
        self.assertEqual(row(self.db, sp.RP_WAIT_KEY)[3], "False")

    def test_a_bad_value_stops_the_start(self):
        for bad in ("maybe", ""):
            with self.subTest(bad=bad):
                r = self.run_entrypoint_line(HEARTHDAOC_BOT_RP_TIMER_WAIT=bad)
                self.assertEqual(r.returncode, 2)
                self.assertEqual(r.stderr, f"ERROR: HEARTHDAOC_BOT_RP_TIMER_WAIT must be on or off, got {bad!r}\n")
                self.assertIsNone(row(self.db, sp.RP_WAIT_KEY))
                self.assertIsNone(row(self.db, sp.OVERRIDES_KEY))  # checked before any write: nothing at all
                self.assertIsNone(row(self.db, sp.SI_KEY))


class SettingDocsTests(unittest.TestCase):
    def test_compose_passes_the_setting_with_default_on(self):
        environment = read("compose.yml").split("\n    environment:\n", 1)[1].split("\n    volumes:\n", 1)[0]
        self.assertIn("\n      HEARTHDAOC_BOT_RP_TIMER_WAIT: ${HEARTHDAOC_BOT_RP_TIMER_WAIT-on}\n", environment + "\n")

    def test_env_example_documents_the_setting_default_on(self):
        lines = read(".env.example").splitlines()
        self.assertEqual([line for line in lines if line.startswith("HEARTHDAOC_BOT_RP_TIMER_WAIT")],
                         ["HEARTHDAOC_BOT_RP_TIMER_WAIT=on"])
        i = lines.index("HEARTHDAOC_BOT_RP_TIMER_WAIT=on")
        comment = []
        while i > 0 and lines[i - 1].startswith("#"):
            i -= 1
            comment.insert(0, lines[i])
        self.assertIn("realm points", " ".join(comment))
        self.assertIn("off =", " ".join(comment))

    def test_handoff_lists_the_setting(self):
        handoff = read("HANDOFF.md")
        self.assertIn("`HEARTHDAOC_BOT_RP_TIMER_WAIT` (default `on`", handoff)
        self.assertIn("`HEARTHDAOC_BOT_RP_TIMER_WAIT=on`", handoff)  # what ./hdc update adds to an existing .env


class ServerDeclarationTests(unittest.TestCase):
    def test_server_declares_the_property_with_the_same_description(self):
        with open(SCRIPT_CS, encoding="utf-8") as f:
            found = re.findall(r'\[ServerProperty\(\s*"([^"]*)",\s*"bot_rp_timer_wait",\s*"([^"]*)",\s*(\w+)\s*\)\]', f.read())
        self.assertEqual(found, [("server", sp.RP_WAIT_DESCRIPTION, "false")])


if __name__ == "__main__":
    unittest.main()

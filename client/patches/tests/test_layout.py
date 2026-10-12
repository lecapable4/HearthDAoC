"""Tests for the default layout patch set: its generator (layout.py) and the committed default-layout.json.

The block's rules run on a made-up character file and a made-up default.ini. The committed patch set is checked
on its own (its block follows the rules), against OfflineDAoC 0.35's default.ini when HDC_CLIENT_FILES holds it
(the hashes, the client's lookup for a new character, apply, re-apply and restore, and a rebuild from its own
block), and against the character's settings file it was made from when HDC_LAYOUT_FROM names it.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PATCHES = os.path.dirname(HERE)
sys.path.insert(0, PATCHES)
import layout  # noqa: E402
import patchset  # noqa: E402
from build import to_json  # noqa: E402

COMMITTED = os.path.join(PATCHES, "default-layout.json")
CLIENT = os.environ.get("HDC_CLIENT_FILES")
REAL_INI = os.path.join(CLIENT, "default.ini") if CLIENT else None
LAYOUT_FROM = os.environ.get("HDC_LAYOUT_FROM")
NEEDS_INI = "set HDC_CLIENT_FILES to a folder with OfflineDAoC 0.35's default.ini"

# A character's settings file as the client writes it (CRLF, a blank line after some sections, LFGClass2 twice, the
# second with the bytes the client leaks), with hotkeys, a macro, a quick-bind and a housing help flag.
CHARACTER = "\r\n".join([
    "[Panels]", "Version=1", "Alpha=100", "ChatWindow0=Main,295,849,801,231,58,100,10,1,0,1", "LFG=50,50,100,100",
    "LFGOptions=1,0,1,0", "LFGLevels=21,27", "LFGPurposeFlags=0,0,0,172,31,51,119,92,31,51,119",
    "LFGClass0=1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1", "LFGClass1=0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0",
    "LFGClass2=0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0", "LFGClass2=80,97,110,101,108,115,0,49,57,50,48,0,0,0,0,0",
    "Quickbar=0,0,1,1,100,0,1", "Quickbar2=0,33,1,0,100,0,1",
    "[Quickbar]", "GroupSize=10", "Hotkey_0=35,2,Uppercut,602", "Hotkey_9=10,0,Aggravate,1586",
    "[Quickbar2]", "GroupSize=10", "Hotkey_0=10,5,Aura of Indestructability,997",
    "[Quickbar3]", "GroupSize=10",
    "[Macros]", "Macro_0=hi,/say hi",
    "[Chat]", "ChannelVer=1", "ChatColors0=0,0,8,17", "IgnoreChatScrolling0=1",
    "[NameOptions]", "Version=3", "Visibility=127", "Coloring=1", "",
    "[QuickBinds]", "QuickBind_0=1,2", "",
    "[HouseHelp]", "HasSeen01=1", "",
    "[Camera]", "distance=500.00", "height=10.00", "tilt=174", "angle=0",
    "[ToolTips]", "ToolTipAlphaChoice=1", "ToolTipDelay=0", ""])
BLOCK = "\r\n".join([
    "[Panels-1920x1080]", "Version=1", "Alpha=100", "ChatWindow0=Main,295,849,801,231,58,100,10,1,0,1",
    "LFG=50,50,100,100", "LFGOptions=0,0,0,0", "LFGLevels=1,2", "LFGPurposeFlags=0,0,0,0,0,0,0,0,0,0,0",
    "LFGClass0=0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0", "LFGClass1=0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0",
    "LFGClass2=0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0", "LFGClass2=0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0",
    "Quickbar=0,0,1,1,100,0,1", "Quickbar2=0,33,1,0,100,0,1",
    "[Quickbar]", "GroupSize=10", "[Quickbar2]", "GroupSize=10", "[Quickbar3]", "GroupSize=10",
    "[Macros]", "[QuickBinds]", "[HouseHelp]",
    "[Chat]", "ChannelVer=1", "ChatColors0=0,0,8,17", "IgnoreChatScrolling0=1",
    "[NameOptions]", "Version=3", "Visibility=127", "Coloring=1",
    "[Camera]", "distance=500.00", "height=10.00", "tilt=174", "angle=0",
    "[ToolTips]", "ToolTipAlphaChoice=1", "ToolTipDelay=0", ""])


def stock_block(resolution, x):
    return [f"[Panels-{resolution}]", "Version=1", f"ChatWindow0=Main,{x},600,396,200,58,100,10,1,0,1",
            "[Quickbar]", "GroupSize=10", "[Chat]", "ChannelVer=1", "ChatColors0=9,9,9,9",
            "[NameOptions]", "Version=3", "Visibility=126", "Coloring=1", "", "[Camera]", "distance=500.00",
            "[ToolTips]", "ToolTipDelay=0", "", ""]


# A made-up default.ini in the stock file's shape: a block per resolution, 800x600 first.
STOCK_INI = "\r\n".join(stock_block("800x600", 10) + stock_block("1920x1080", 20)
                        + stock_block("2560x1440", 30)).encode("latin-1")
STOCK_INI_PATCHED = BLOCK.encode("latin-1") + STOCK_INI


def fixture_layout_set():
    """The default-layout patch set for STOCK_INI, as layout.py makes it for the real file."""
    return {"format": 1, "name": "default-layout", "client": "test fixture", "refused": layout.REFUSED,
            "files": [layout.layout_entry(STOCK_INI, BLOCK)]}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    with open(path, "rb") as f:
        return f.read()


def client_value(text, section, key):
    """What the client reads for `key` in `section` (game.dll 0x731a23 and 0x731acf): from the top of the file,
    the first [section] line, without case, then the first line of that key, without case, before the next
    section; None when there is none."""
    lines = text.split("\r\n")
    for i, line in enumerate(lines):
        if line.lower() == f"[{section}]".lower():
            for line in lines[i + 1:]:
                if line.startswith("["):
                    return None
                name, equals, value = line.partition("=")
                if equals and name.lower() == key.lower():
                    return value
            return None
    return None


def new_character(text, resolution, block=BLOCK):
    """{(section, key): value} a new character at `resolution` reads from a default.ini's text, for the keys of
    `block`'s sections: [Panels-<resolution>] for the panels, the others by name."""
    out = {}
    for name, lines in layout.sections(block):
        section = f"Panels-{resolution}" if name.startswith("Panels-") else name
        for line in lines:
            key = line.partition("=")[0]
            out[(name.split("-")[0], key)] = client_value(text, section, key)
    return out


def committed():
    with open(COMMITTED, encoding="utf-8") as f:
        return json.load(f)


def committed_block():
    replace = committed()["files"][0]["ops"][0]["replace"]
    return replace[:-len(layout.ANCHOR)]


def as_character_file(block):
    """The block as a character's settings file: its [Panels-<resolution>] called [Panels]."""
    return "[Panels]\r\n" + block.split("\r\n", 1)[1]


class BlockTests(unittest.TestCase):
    def test_keeps_the_panels_and_copied_sections_and_resets_the_looking_for_group_keys(self):
        self.assertEqual(layout.layout_block(CHARACTER), BLOCK)

    def test_no_hotkey_macro_quick_bind_or_housing_flag_is_kept(self):
        for text in ("Hotkey_", "Macro_", "QuickBind_", "HasSeen", "21,27", "80,97"):
            self.assertNotIn(text, layout.layout_block(CHARACTER), text)

    def test_lines_end_in_crlf_whatever_the_file_used(self):
        block = layout.layout_block(CHARACTER.replace("\r\n", "\n"))
        self.assertEqual(block, BLOCK)
        self.assertEqual(block.count("\n"), block.count("\r\n"))

    def test_sections_are_found_without_case_as_the_client_finds_them(self):
        self.assertEqual(layout.layout_block(CHARACTER.replace("[Panels]", "[PANELS]").replace("[Chat]", "[chat]")),
                         BLOCK)

    def test_only_the_first_section_of_a_name_counts(self):
        later = CHARACTER + "[Camera]\r\ndistance=1.00\r\n[Panels]\r\nVersion=9\r\n"
        self.assertEqual(layout.layout_block(later), BLOCK)

    def test_another_resolution(self):
        self.assertEqual(layout.layout_block(CHARACTER, "2560x1440"), BLOCK.replace("1920x1080", "2560x1440"))
        for bad in ("1920*1080", "x1080", "0x0", "1920x1080 "):
            with self.subTest(bad), self.assertRaisesRegex(ValueError, "resolution"):
                layout.layout_block(CHARACTER, bad)

    def test_a_file_without_a_needed_section_is_refused(self):
        for name in ["Panels"] + layout.COPIED:
            text = CHARACTER.replace(f"[{name}]", "[Other]")
            with self.subTest(name), self.assertRaisesRegex(ValueError, rf"x.ini has no \[{name}\] section"):
                layout.layout_block(text, source="x.ini")

    def test_the_rules_hold_for_their_own_block(self):
        self.assertEqual(layout.layout_block(as_character_file(BLOCK)), BLOCK)


class EntryTests(unittest.TestCase):
    def test_the_block_goes_at_the_top_of_default_ini(self):
        entry = layout.layout_entry(STOCK_INI, BLOCK)
        self.assertEqual(entry, {"path": "default.ini", "before": sha(STOCK_INI), "after": sha(STOCK_INI_PATCHED),
                                 "ops": [{"op": "text-replace", "find": "[Panels-800x600]\r\n",
                                          "replace": BLOCK + "[Panels-800x600]\r\n"}]})
        self.assertEqual(patchset.transform(STOCK_INI, entry["ops"], None), STOCK_INI_PATCHED)

    def test_a_new_character_at_that_resolution_gets_the_block(self):
        values = new_character(STOCK_INI_PATCHED.decode("latin-1"), "1920x1080")
        self.assertEqual(values[("Panels", "ChatWindow0")], "Main,295,849,801,231,58,100,10,1,0,1")
        self.assertEqual(values[("Panels", "LFGLevels")], "1,2")
        self.assertEqual(values[("NameOptions", "Visibility")], "127")
        self.assertEqual(values[("Chat", "ChatColors0")], "0,0,8,17")
        self.assertEqual(values, new_character(BLOCK, "1920x1080"))

    def test_other_resolutions_keep_the_stock_panels_with_the_block_s_other_sections(self):
        text = STOCK_INI_PATCHED.decode("latin-1")
        self.assertEqual(client_value(text, "Panels-2560x1440", "ChatWindow0"), "Main,30,600,396,200,58,100,10,1,0,1")
        self.assertEqual(client_value(text, "Panels-800x600", "ChatWindow0"), "Main,10,600,396,200,58,100,10,1,0,1")
        self.assertEqual(client_value(text, "NameOptions", "Visibility"), "127")
        self.assertEqual(client_value(STOCK_INI.decode("latin-1"), "NameOptions", "Visibility"), "126")

    def test_refuses_a_file_that_does_not_start_with_the_anchor_or_holds_it_twice(self):
        for data in (b"; comment\r\n" + STOCK_INI, STOCK_INI + b"[Panels-800x600]\r\n"):
            with self.subTest(data[:12]), self.assertRaises(ValueError):
                layout.layout_entry(data, BLOCK)

    def test_build_refuses_a_default_ini_that_is_not_offlinedaocs(self):
        with tempfile.TemporaryDirectory() as tmp:
            character = os.path.join(tmp, "Charles-5.ini")
            with open(character, "wb") as f:
                f.write(CHARACTER.encode("latin-1"))
            with open(os.path.join(tmp, "default.ini"), "wb") as f:
                f.write(STOCK_INI)
            with self.assertRaisesRegex(ValueError, "default.ini is not OfflineDAoC 0.35's file"):
                layout.build_patchset(character, tmp)
            r = subprocess.run([sys.executable, os.path.join(PATCHES, "layout.py"), "--from", character,
                                "--client", tmp, "--out", os.path.join(tmp, "out.json")], capture_output=True, text=True)
            self.assertEqual((r.returncode, r.stdout), (1, ""))
            self.assertIn("layout.py: default.ini is not OfflineDAoC 0.35's file", r.stderr)
            self.assertFalse(os.path.exists(os.path.join(tmp, "out.json")))


class CommittedSetTests(unittest.TestCase):
    """default-layout.json as it ships: Charles Martel's layout at 1920x1080 for OfflineDAoC 0.35's default.ini."""

    def test_is_a_valid_patch_set_for_default_ini_alone(self):
        data = patchset.load(COMMITTED)
        self.assertEqual([data[key] for key in ("format", "name", "client", "refused")],
                         [1, "default-layout", layout.CLIENT, layout.REFUSED])
        [entry] = data["files"]
        self.assertEqual((entry["path"], entry["before"]), ("default.ini", layout.DEFAULT_INI_SHA256))
        [op] = entry["ops"]
        self.assertEqual((op["op"], op["find"]), ("text-replace", layout.ANCHOR))
        self.assertTrue(op["replace"].endswith(layout.ANCHOR))

    def test_its_block_follows_the_rules(self):
        block = committed_block()
        self.assertTrue(block.startswith("[Panels-1920x1080]\r\n"))
        self.assertEqual(layout.layout_block(as_character_file(block)), block)
        self.assertEqual([name for name, _lines in layout.sections(block)],
                         ["Panels-1920x1080"] + [name for name, _ in layout.EMPTY] + layout.COPIED)
        self.assertEqual(block.count("\n"), block.count("\r\n"))

    def test_it_is_charles_martels_layout(self):
        # The quickbars stacked at the top left, the chat windows side by side along the bottom, the group
        # window at the bottom left, the character sheet at the top right; no menu bar or floating target.
        text = committed_block()
        expected = {
            "Quickbar": "0,0,1,1,100,0,1", "Quickbar2": "0,33,1,0,100,0,1", "Quickbar3": "1359,1039,0,1,100,0,0",
            "ChatWindow0": "Main,295,849,801,231,58,100,10,1,0,1",
            "ChatWindow1": "Combat,1084,849,716,231,38,100,10,1,0,1", "NewGroup": "0,930,1,68,100",
            "Stats": "1459,0,1,6,68,80,68,68,68,68,0,0,100,100,100,100,100,100,68,100",
            "MenuBar": "559,1040,0,68,100", "FloatTarget": "885,755,0,68,100", "LFGLevels": "1,2",
        }
        self.assertEqual({key: client_value(text, "Panels-1920x1080", key) for key in expected}, expected)
        self.assertEqual(len(layout.sections(text)[0][1]), 106)  # every key the client writes, LFGClass2 twice
        self.assertEqual(client_value(text, "NameOptions", "Visibility"), "127")

    def test_the_json_is_the_generator_s_layout(self):
        self.assertEqual(read(COMMITTED), to_json(committed()).encode("ascii"))


@unittest.skipUnless(REAL_INI and os.path.isfile(REAL_INI), NEEDS_INI)
class RealDefaultIniTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stock = read(REAL_INI)

    def test_the_hashes_are_the_real_file_s(self):
        [entry] = committed()["files"]
        self.assertEqual(entry["before"], sha(self.stock))
        self.assertEqual(sha(patchset.transform(self.stock, entry["ops"], None)), entry["after"])

    def test_a_rebuild_from_its_own_block_is_the_committed_file(self):
        character = os.path.join(self.tmp.name, "Charles-5.ini")
        with open(character, "wb") as f:
            f.write(as_character_file(committed_block()).encode("latin-1"))
        self.assertEqual(to_json(layout.build_patchset(character, CLIENT)).encode("ascii"), read(COMMITTED))
        out = os.path.join(self.tmp.name, "default-layout.json")
        r = subprocess.run([sys.executable, os.path.join(PATCHES, "layout.py"), "--from", character, "--client", CLIENT,
                            "--out", out], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read(out), read(COMMITTED))

    def test_a_new_character_gets_the_block_and_other_resolutions_the_stock_panels(self):
        patched = patchset.transform(self.stock, committed()["files"][0]["ops"], None).decode("latin-1")
        stock = self.stock.decode("latin-1")
        block = committed_block()
        self.assertEqual(new_character(patched, "1920x1080", block), new_character(block, "1920x1080", block))
        for key in ("ChatWindow0", "Quickbar", "MenuBar", "Stats"):
            self.assertNotEqual(client_value(stock, "Panels-1920x1080", key), client_value(block, "Panels-1920x1080", key))
            for resolution in ("800x600", "1920x1200", "2560x1440", "3840x2160"):
                self.assertEqual(client_value(patched, f"Panels-{resolution}", key),
                                 client_value(stock, f"Panels-{resolution}", key), (resolution, key))

    def test_it_applies_re_applies_and_restores(self):
        client = os.path.join(self.tmp.name, "client")
        os.makedirs(client)
        shutil.copyfile(REAL_INI, os.path.join(client, "default.ini"))

        def run(*switches):
            return subprocess.run([sys.executable, os.path.join(PATCHES, "apply_patches.py"), "--client", client,
                                   "--patchset", COMMITTED, *switches], capture_output=True, text=True)
        r = run()
        self.assertEqual((r.returncode, r.stdout, r.stderr),
                         (0, "Patched: default.ini (original saved as default.ini.hearthdaoc-orig)\n", ""))
        self.assertEqual(sha(read(os.path.join(client, "default.ini"))), committed()["files"][0]["after"])
        r = run()
        self.assertEqual((r.returncode, r.stdout), (0, "Already patched: default.ini\n"))
        r = run("--restore")
        self.assertEqual((r.returncode, r.stdout), (0, "Restored: default.ini\n"))
        self.assertEqual(sorted(os.listdir(client)), ["default.ini"])
        self.assertEqual(read(os.path.join(client, "default.ini")), self.stock)


@unittest.skipUnless(LAYOUT_FROM and REAL_INI and os.path.isfile(REAL_INI),
                     "set HDC_LAYOUT_FROM to the character's settings file the patch set was made from, and "
                     + NEEDS_INI)
class SourceCharacterTests(unittest.TestCase):
    """The owner's check, with Charles-5.ini from their profile folder (read only)."""

    def test_the_committed_set_is_built_from_it(self):
        self.assertEqual(to_json(layout.build_patchset(LAYOUT_FROM, CLIENT)).encode("ascii"), read(COMMITTED))

    def test_a_new_character_reads_its_values_but_its_hotkeys_and_level_range(self):
        patched = patchset.transform(read(REAL_INI), committed()["files"][0]["ops"], None).decode("latin-1")
        character = read(LAYOUT_FROM).decode("latin-1")
        differ = []
        for name, lines in layout.sections(character):
            section = "Panels-1920x1080" if name == "Panels" else name
            for line in lines:
                key, _equals, value = line.partition("=")
                if client_value(character, name, key) == value and client_value(patched, section, key) != value:
                    differ.append(key)
        self.assertEqual([key for key in differ if not key.startswith("Hotkey_")], ["LFGLevels"])


if __name__ == "__main__":
    unittest.main()

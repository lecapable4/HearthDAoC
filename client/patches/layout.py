#!/usr/bin/env python3
"""Generate HearthDAoC's default layout patch set (default-layout.json).

A character that has no settings file yet (<FirstName>-5.ini in the player's profile folder, which the client
writes the first time the character leaves the world) takes its window layout from the client folder's
default.ini: the section [Panels-<width>x<height>] for the screen size, and [Quickbar], [Chat], [NameOptions],
[Camera], [ToolTips] and the others from the first section of that name in the file. The patch set puts our
block at the top of default.ini, so a new character at that screen size starts with the window layout of one of
our characters, and every new character with its chat, name plate, camera and tooltip settings. Characters that
have a settings file keep theirs.

Reads that character's settings file and an OfflineDAoC 0.35 client's own default.ini, and writes only patch
data: the two SHA-256 hashes and one text edit whose text is our block, followed by the line of default.ini it
goes in front of. No EA file is copied into the patch set. Running it twice on the same inputs gives
byte-identical output.

The block keeps every [Panels] key of the character in its order, but the looking-for-group keys, which follow
the character (its level range), get a new character's values. Its quickbars hold no hotkeys (they point at the
character's own spells, styles and backpack slots), and [Macros], [QuickBinds] and [HouseHelp] are empty.
[Chat], [NameOptions], [Camera] and [ToolTips] are copied. Lines end in CRLF, as the client writes them.

  python3 client/patches/layout.py --from ".../Dark Age of Camelot/OfflineDAoC03/Charles-5.ini" \\
      --client <folder with OfflineDAoC 0.35's default.ini> --out client/patches/default-layout.json
"""
import argparse
import re
import sys

from build import edit_text, file_entry, read_client_file, sha256, to_json

FORMAT = 1
NAME = "default-layout"
CLIENT = "OfflineDAoC 0.35 (both editions)"
DEFAULT_INI = "default.ini"
DEFAULT_INI_SHA256 = "f43e1b5df8e7d595f132319be99b52647b12e92bf706d43ba8bd6ed3fbb1d343"
# default.ini's first line. The block goes in front of it, so each of its sections is the first of its name.
ANCHOR = "[Panels-800x600]\r\n"
RESOLUTION = "1920x1080"
# What the appliers print after "Not patched: default.ini is not the file this HearthDAoC release supports ".
REFUSED = ("(for example one changed by hand, or an older or newer upstream client). New characters start with "
           "the game's standard window layout.")
# The looking-for-group keys follow the character: a new character's values (the client writes LFGClass2 twice).
LFG_RESET = {"LFGOptions": "0,0,0,0", "LFGLevels": "1,2", "LFGPurposeFlags": ",".join(["0"] * 11)}
LFG_CLASS = re.compile(r"LFGClass[0-9]+")
LFG_CLASS_RESET = ",".join(["0"] * 16)
# The character's own hotkeys, macros, quick-binds and housing help flags: none in the block. A quickbar keeps
# the client's own size.
EMPTY = [("Quickbar", ["GroupSize=10"]), ("Quickbar2", ["GroupSize=10"]), ("Quickbar3", ["GroupSize=10"]),
         ("Macros", []), ("QuickBinds", []), ("HouseHelp", [])]
# Copied as they are: the chat windows' colours and channels, name plates, camera and tooltips.
COPIED = ["Chat", "NameOptions", "Camera", "ToolTips"]


def sections(text: str) -> list[tuple[str, list[str]]]:
    """[(name, lines)] of an .ini text in file order, without blank lines; repeated sections and keys are kept."""
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith("[") and line.endswith("]"):
            out.append((line[1:-1], []))
        elif line and out:
            out[-1][1].append(line)
    return out


def section(found: list[tuple[str, list[str]]], name: str, source: str) -> list[str]:
    """The lines of the first section called `name`, without case, as the client reads it."""
    for section_name, lines in found:
        if section_name.lower() == name.lower():
            return lines
    raise ValueError(f"{source} has no [{name}] section: give a character's settings file as the client "
                     "writes it (<Name>-5.ini)")


def layout_block(character: str, resolution: str = RESOLUTION, source: str = "the character file") -> str:
    """Our block for the top of default.ini, from a character's settings file (its text, `character`): its
    [Panels] as [Panels-<resolution>], empty quickbars, macros, quick-binds and housing help flags, and its
    [Chat], [NameOptions], [Camera] and [ToolTips]."""
    if not re.fullmatch(r"[1-9][0-9]*x[1-9][0-9]*", resolution):
        raise ValueError(f"the resolution must look like {RESOLUTION}: {resolution!r}")
    found = sections(character)
    lines = [f"[Panels-{resolution}]"]
    for line in section(found, "Panels", source):
        key, equals, _value = line.partition("=")
        if equals and key in LFG_RESET:
            line = f"{key}={LFG_RESET[key]}"
        elif equals and LFG_CLASS.fullmatch(key):
            line = f"{key}={LFG_CLASS_RESET}"
        lines.append(line)
    for name, keep in EMPTY:
        lines += [f"[{name}]", *keep]
    for name in COPIED:
        lines += [f"[{name}]", *section(found, name, source)]
    return "\r\n".join(lines) + "\r\n"


def check_default_ini(original: bytes) -> None:
    """ValueError unless `original` is OfflineDAoC 0.35's default.ini."""
    if sha256(original) != DEFAULT_INI_SHA256:
        raise ValueError(f"{DEFAULT_INI} is not OfflineDAoC 0.35's file (SHA-256 {DEFAULT_INI_SHA256})")


def layout_entry(original: bytes, block: str) -> dict:
    """The patch-set entry that puts `block` at the top of default.ini (`original`, the client's own)."""
    if not original.startswith(ANCHOR.encode("latin-1")):
        raise ValueError(f"{DEFAULT_INI} doesn't start with {ANCHOR.strip()}")
    edits = [(ANCHOR, block + ANCHOR)]
    ops = [{"op": "text-replace", "find": find, "replace": replace} for find, replace in edits]
    return file_entry(DEFAULT_INI, original, edit_text(original, edits), ops)


def build_patchset(character_ini: str, client_dir: str, resolution: str = RESOLUTION) -> dict:
    """The default-layout patch set: the layout of the character whose settings file is `character_ini`, for
    new characters at `resolution`, on the default.ini in `client_dir`."""
    with open(character_ini, "rb") as f:
        block = layout_block(f.read().decode("latin-1"), resolution, character_ini)
    original = read_client_file(client_dir, DEFAULT_INI)
    check_default_ini(original)
    return {"format": FORMAT, "name": NAME, "client": CLIENT, "refused": REFUSED,
            "files": [layout_entry(original, block)]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate HearthDAoC's default layout patch set.")
    parser.add_argument("--from", dest="character", required=True,
                        help="the settings file of the character whose layout new characters get (<Name>-5.ini)")
    parser.add_argument("--client", required=True, help="a folder with OfflineDAoC 0.35's default.ini (read only)")
    parser.add_argument("--resolution", default=RESOLUTION,
                        help=f"the screen size the layout is for (default {RESOLUTION})")
    parser.add_argument("--out", required=True, help="the patch set to write")
    args = parser.parse_args(argv)
    try:
        patchset = build_patchset(args.character, args.client, args.resolution)
    except (OSError, ValueError) as e:
        print(f"layout.py: {e}", file=sys.stderr)
        return 1
    with open(args.out, "w", encoding="ascii", newline="\n") as f:
        f.write(to_json(patchset))
    print(f"Wrote {args.out}: {DEFAULT_INI}, [Panels-{args.resolution}] from {args.character}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

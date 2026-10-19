"""Line endings of the upstream files the fork edits, checked against upstream's own (the 0.37 sync's review, finding
code-2; tests in test_endings.py).

Upstream ships some files with both endings: v0.36b's GamePlayer.cs has 103 LF lines among 13,574 CRLF ones, v0.37b's
GameLiving.cs 101 among 3,817, and v0.37b's ClassicQuests.cs is an LF file with 14 CRLF lines (ScaleXP). So "one
ending per file" fails on upstream's own files, while a fork line written in a file's other ending, or a whole file
normalised, is what the check is for. problems() compares a file with upstream's version of it, line by line on
their text (difflib):
- a line upstream has too keeps upstream's ending;
- a fork line (what upstream lacks: the HearthDAoC-marked hooks and the lines of their blocks) has the ending of an
  upstream line beside it, the one above or the one below.
Upstream's version is the file at deploy/upstream.lock's tag, or at its commit when the tag is not fetched (the sync
merges upstream's commit, so a clone with history has it). Without either (a shallow clone), the fork lines are the
marked lines and the lines of their blocks (the lines after a mark up to a blank line or a line indented less), and
every other line must have the file's majority ending; a file upstream ships with both endings then fails, and the
message says to fetch the tag.
"""
import collections
import difflib
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCK = os.path.join(ROOT, "deploy", "upstream.lock")
BOM = b"\xef\xbb\xbf"
MARK = b"HearthDAoC:"
NAMES = {b"\r\n": "CRLF", b"\n": "LF", b"": "no line end"}
NO_UPSTREAM = "upstream's version is not in this repository: fetch the lock's tag to compare with its own endings"


def git_show(rev, rel):
    """The bytes of rel (a path from the repository root) at rev, or None when this repository lacks either."""
    try:
        r = subprocess.run(["git", "-C", ROOT, "show", f"{rev}:{rel}"], capture_output=True,
                           env=dict(os.environ, LC_ALL="C"))
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


def upstream_rev():
    """The lock's tag, or its commit when the tag is not in this repository, or None when neither is."""
    with open(LOCK, encoding="utf-8") as f:
        lock = json.load(f)
    for rev in (lock.get("tag"), lock.get("commit")):
        if rev and subprocess.run(["git", "-C", ROOT, "rev-parse", "-q", "--verify", f"{rev}^{{commit}}"],
                                  capture_output=True, env=dict(os.environ, LC_ALL="C")).returncode == 0:
            return rev
    return None


def upstream_blob(path):
    """Upstream's version of the file at path (absolute, or from the repository root) at upstream_rev(), or None."""
    rev = upstream_rev()
    rel = os.path.relpath(os.path.join(ROOT, path), ROOT).replace(os.sep, "/")
    return git_show(rev, rel) if rev else None


def lines(raw):
    """[(text, end)] of raw without its BOM; end is CRLF, LF or b"" (a last line without one)."""
    body = raw[len(BOM):] if raw.startswith(BOM) else raw
    parts = body.split(b"\n")
    out = [(p[:-1], b"\r\n") if p.endswith(b"\r") else (p, b"\n") for p in parts[:-1]]
    if parts[-1]:
        out.append((parts[-1], b""))
    return out


def marked_blocks(ours):
    """The indexes of the fork's lines by its marks: each marked line, and the lines after it up to a blank line or a
    line indented less."""
    fork = set()
    for n, (text, _) in enumerate(ours):
        if MARK not in text:
            continue
        fork.add(n)
        indent = len(text) - len(text.lstrip())
        for m in range(n + 1, len(ours)):
            after = ours[m][0]
            if not after.strip() or len(after) - len(after.lstrip()) < indent:
                break
            fork.add(m)
    return fork


def problems(raw, upstream=None):
    """What is wrong with raw's line endings, against upstream's version of the file (bytes; None: by the marks and the
    file's majority, as in a shallow clone): [] when nothing is."""
    ours = lines(raw)
    found = [f"line {n} has a lone CR" for n, (text, _) in enumerate(ours, 1) if b"\r" in text]
    if upstream is not None:
        if raw.startswith(BOM) != upstream.startswith(BOM):
            found.append("the file has a BOM and upstream's has none" if raw.startswith(BOM)
                         else "the file lacks upstream's BOM")
        theirs = lines(upstream)
        matcher = difflib.SequenceMatcher(None, [t for t, _ in ours], [t for t, _ in theirs], autojunk=False)
        want = [None] * len(ours)  # upstream's ending of each line upstream has too
        for i, j, size in matcher.get_matching_blocks():
            for k in range(size):
                want[i + k] = theirs[j + k][1]
        why = "upstream's {}"
    else:
        fork = marked_blocks(ours)
        counts = collections.Counter(end for n, (_, end) in enumerate(ours) if end and n not in fork)
        majority = counts.most_common(1)[0][0] if counts else None
        want = [None if n in fork else majority for n in range(len(ours))]
        why = "the file's majority {} (" + NO_UPSTREAM + ")"
    for n, (_, end) in enumerate(ours):
        if not end:
            continue  # the last line, without a line end
        if want[n] is not None:
            if end != want[n]:
                found.append(f"line {n + 1} ends {NAMES[end]}, " + why.format(NAMES[want[n]]))
            continue
        above = next((want[m] for m in range(n - 1, -1, -1) if want[m]), None)
        below = next((want[m] for m in range(n + 1, len(ours)) if want[m]), None)
        beside = [e for e in (above, below) if e]
        if beside and end not in beside:
            found.append(f"line {n + 1} (a fork line) ends {NAMES[end]}, the upstream lines beside it "
                         + " and ".join(dict.fromkeys(NAMES[e] for e in beside)))
    return found


def check(test, path):
    """test fails, naming each line, when path's line endings are not upstream's (problems())."""
    with open(path, "rb") as f:
        raw = f.read()
    test.assertEqual(problems(raw, upstream_blob(path)), [], path)

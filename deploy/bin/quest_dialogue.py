#!/usr/bin/env python3
"""Quest texts in the world data: the Guild of Shadows chain's dialogue (levels 7 to 50), and the classic quests'
period lines, names and class words, without the guides' leftovers.

Upstream left most of the chain's text empty ("[Traveler's]") or filled with walkthrough notes. Its generator also lost
the line that offers some classic quests (level 5's "Cleric Mulgrut" at Hugh Gallen showed only his wares) and wrote
<Player>, which the server replaces with the player's name, where the period named someone else (Durren, Askheim, ...)
or said a plain word ("Well", Wariel's "What is your [name]?"). It also kept the class the period guides' authors were
called by ("Good luck to thee Theurgist.") and the guides' placeholders for it ("(class name)"), which every class read:
the file says <Class>, which the server replaces with the player's class, and New Crest's accept keyword, which
DataQuest compares as it is, is each row's own class. The guides' placeholder for the player's name ("(your name
here)", and The Lost Stone's whisper keyword "<your name>", which DataQuest now matches as the player reads it) is
<Player>, and what is no one's words is cut: the web page upstream scraped after Mystemas's last line, and the kill
tasks' notes on Allakhazam. The texts are in quest_dialogue.json, beside this file;
world_fixes.py calls apply() inside its transaction, right after epic_chains.apply() (the chain's rows, including the
fork's own level-50 ones, must exist), under its own savepoint: if it fails it is rolled back alone, apply() returns
only the "not applied" line, and the other fixes and the start go on.

Unlike the other world fixes this one has no marker. It runs at every start and changes a row only while the columns
it sets still hold a text the file's guard lists: upstream's (as epic_chains.py leaves them) or an earlier version of
this file's text. So the owner's own edits stay, and a later revision of the text reaches a world that had an earlier
one. A row that already holds the new text is left alone. Rows left alone for any other reason are named by quest ID
in the start log at every start, so a quest whose upstream text an upgrade changed (and which therefore keeps
upstream's text) is seen.

The file:
  {"quests": [{"step": "7", "set": {...}, "guard": {"21500": ["<digest>", ...]}},
              {"ids": [20207], "name": "Cleric Mulgrut", "set": {...}, "guard": {"20207": ["<digest>", ...]}}]}
- step: a key of epic_chains_data.json "steps"; its "ids" are the quest IDs of the classes, in that file's order
  ("classes"); a null ID is skipped.
- ids: instead of a step, plain quest IDs (the classic quests), which get the same text; a per-class object is refused.
  name is for the reader. A quest ID is in one entry only.
- set: DataQuest columns to set (AcceptText, Description, SourceText, StepType, StepText, TargetText, AdvanceText,
  FinishText, StepItemTemplates, CollectItemTemplate, StartName, QuestDependency). A value is a string (every class),
  an object with all five class names, or (for the per-stage columns SourceText, StepType, StepText, TargetText,
  AdvanceText, StepItemTemplates, CollectItemTemplate) a list with one entry, a string or a per-class object, for each
  stage of the quest row (its StepType split on "|"); the list is joined with "|". No value may contain "|", but
  QuestDependency's, whose entries it separates as DataQuest reads them (a single value, as epic_chains.py writes it:
  "#21500/21324|!#20469"). StartName (the giver) and QuestDependency are never lists. StepType is always such a list,
  of numbers (eStepType): the fix may change a stage's type but never the number of stages. A quest row with another
  number of stages than a list has entries is left alone and named with the other rows left alone; the other rows
  still apply.
- guard: for each quest ID, the digests of its `set` columns' values that may be replaced. digest() makes them.
  `quest_dialogue.py --seal` appends to every quest's guard list the digest of the file's own current text for that
  quest (computed from the file alone, no world needed). `--digests WORLD.db` prints the digests of the text WORLD
  holds (after epic_chains), by step or ids, which is upstream's text only on a clean world; with `--current` it
  applies this file to its copy first. It is needed for a new entry (upstream's digests start its guard lists) and
  when an entry's set of columns changes: old worlds' values are digested over the new column set, which only a world
  can give.

To revise the text: edit it, run
  python3 deploy/bin/quest_dialogue.py --seal
and commit (a test fails until you do). Every committed version of the text is then guarded, so a later revision
reaches a world that holds any earlier committed version. Keep each entry's `set` columns: the digests cover exactly
those columns (to change them, see `--digests`).
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile

import epic_chains

SAVEPOINT = "quest_dialogue"
NOT_APPLIED = "Quest dialogue: not applied ({}); the quests keep the text they have"
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quest_dialogue.json")
COLUMNS = ("AcceptText", "Description", "SourceText", "StepType", "StepText", "TargetText", "AdvanceText", "FinishText",
           "StepItemTemplates", "CollectItemTemplate", "StartName", "QuestDependency")
PER_STAGE = ("SourceText", "StepType", "StepText", "TargetText", "AdvanceText", "StepItemTemplates", "CollectItemTemplate")
PIPED = ("QuestDependency",)  # one value whose own entries "|" separates: no stages


def load_data(path=DATA_FILE):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def digest(values):
    """The guard digest of a row's `set` columns: `values` in sorted column-name order (None counts as "")."""
    return hashlib.sha256(json.dumps([value or "" for value in values], ensure_ascii=False).encode("utf-8")).hexdigest()


def _per_class(value, classes, what, piped=False):
    """A string for every class, or an object with all the class names: {class name: string}. Only a `piped` column's
    value may contain "|"."""
    if isinstance(value, str):
        if "|" in value and not piped:
            raise ValueError(f"{what}: a value contains '|'")
        return {name: value for name in classes}
    if not isinstance(value, dict):
        raise ValueError(f"{what}: expected a string or a per-class object")
    missing = [name for name in classes if name not in value]
    unknown = [name for name in value if name not in classes]
    if missing or unknown:
        raise ValueError(f"{what}: " + ("missing class " + ", ".join(missing) if missing else "unknown class " + ", ".join(unknown)))
    return _per_class_strings(value, what, piped)


def _per_class_strings(value, what, piped=False):
    for text in value.values():
        if not isinstance(text, str):
            raise ValueError(f"{what}: a per-class value is not a string")
        if "|" in text and not piped:
            raise ValueError(f"{what}: a value contains '|'")
    return dict(value)


def resolve(column, value, classes, stages):
    """The text of `column` for each class: {class name: text}. `stages` is {class name: number of stages}; a class
    whose quest row has another number of stages than a per-stage list has entries gets None (that row is left alone)."""
    what = column
    if column not in COLUMNS:
        raise ValueError(f"unknown column {column}")
    if not isinstance(value, list):
        if column == "StepType":  # a string would be one stage: the number of stages never changes here
            raise ValueError(f"{what}: a list with one entry for each stage")
        return _per_class(value, classes, what, column in PIPED)
    if column not in PER_STAGE:
        raise ValueError(f"{what}: a list is only for the per-stage columns")
    entries = [_per_class(entry, classes, what) for entry in value]
    if column == "StepType" and any(not re.fullmatch(r"[0-9]+", text) for entry in entries for text in entry.values()):
        raise ValueError(f"{what}: a stage's type is not a number")
    out = {}
    for name in classes:
        if stages[name] is not None and len(value) != stages[name]:
            out[name] = None
        else:
            out[name] = "|".join(entry[name] for entry in entries)
    return out


def _rows(conn, ids):
    """{quest id: StepType} of the rows that exist."""
    marks = ", ".join("?" * len(ids))
    return {qid: stype for qid, stype in conn.execute(f"SELECT ID, IFNULL(StepType, '') FROM DataQuest WHERE ID IN ({marks})", ids)}


def label(entry):
    """How --digests names an entry: its step, or "ids" and its quest IDs."""
    return entry["step"] if "step" in entry else "ids " + ", ".join(str(qid) for qid in entry["ids"])


def _quests(entry, chains):
    """(names, {name: quest id}): the quests an entry rewrites, by the names its values are given for. A step's names
    are the classes (a null ID is skipped). An ids entry has one text for all its quests, named by their IDs."""
    if ("step" in entry) == ("ids" in entry):
        raise ValueError("an entry names a step or ids, one of them")
    if "step" in entry:
        step = entry["step"]
        if step not in chains["steps"]:
            raise ValueError(f"unknown step {step}")
        classes = list(chains["classes"])
        return classes, {name: qid for name, qid in zip(classes, chains["steps"][step]["ids"]) if qid is not None}
    ids = entry["ids"]
    if not isinstance(ids, list) or not ids or any(type(qid) is not int for qid in ids) or len(set(ids)) != len(ids):
        raise ValueError(f"ids {ids!r}: a list of quest IDs, each once")
    for column, value in entry["set"].items():
        if any(isinstance(part, dict) for part in (value if isinstance(value, list) else [value])):
            raise ValueError(f"quests {', '.join(map(str, ids))}: {column} has a per-class object, which only a step's "
                             "entry takes")
    return [str(qid) for qid in ids], {str(qid): qid for qid in ids}


def _plan(conn, data, chains):
    """The work: [(quest id, columns in sorted order, new values, guard digests)], after checking the whole file. The
    new values are None for a row whose number of stages (its StepType) is not the length of a per-stage list: the
    owner or a later world changed that quest's steps, so the file's text doesn't fit it, and the row is left alone
    (the other rows still apply)."""
    plan, seen, quests = [], set(), set()
    for entry in data.get("quests", []):
        if "step" in entry:
            if entry["step"] in seen:
                raise ValueError(f"step {entry['step']} appears twice")
            seen.add(entry["step"])
        names, by_name = _quests(entry, chains)
        for qid in by_name.values():
            if qid in quests:
                raise ValueError(f"quest {qid} is in two entries")
            quests.add(qid)
        columns = sorted(entry["set"])
        stype = _rows(conn, list(by_name.values())) if by_name else {}
        stages = {name: (len(stype[qid].split("|")) if qid in stype else None) for name, qid in by_name.items()}
        for name in names:
            stages.setdefault(name, None)
        resolved = {column: resolve(column, entry["set"][column], names, stages) for column in columns}
        for name, qid in by_name.items():
            values = [resolved[column][name] for column in columns]
            plan.append((qid, columns, None if None in values else values,
                         set(entry.get("guard", {}).get(str(qid), []))))
    return plan


def apply(conn, now=None, data=None, chains=None):
    """Rewrite the quests' texts where they still hold a known earlier text; returns the summary line, the "not
    applied" line, or nothing. `chains` is epic_chains_data.json's contents.

    Inside an open transaction (world_fixes.py's), nothing here commits; on a connection with none open, the
    savepoint is the transaction, and its release commits it."""
    tables = {name.lower() for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "dataquest" not in tables:
        return []
    now = now or _now()
    conn.execute(f"SAVEPOINT {SAVEPOINT}")
    try:
        data = data if data is not None else load_data()
        chains = chains if chains is not None else epic_chains.load_data()
        rewritten, kept = 0, []
        for qid, columns, values, guard in _plan(conn, data, chains):
            row = conn.execute(f"SELECT {', '.join(columns)} FROM DataQuest WHERE ID=?", (qid,)).fetchone()
            if row is None:
                continue
            if values is None:  # its stages differ from the file's
                kept.append(qid)
                continue
            held = [value or "" for value in row]
            if held == values:
                continue
            if digest(held) not in guard:
                kept.append(qid)
                continue
            sets = ", ".join(f"{column}=?" for column in columns)
            conn.execute(f"UPDATE DataQuest SET {sets}, LastTimeRowUpdated=? WHERE ID=?", (*values, now, qid))
            rewritten += 1
    except Exception as e:  # any failure: undo this fix only, and let the other fixes and the start go on
        conn.execute(f"ROLLBACK TO {SAVEPOINT}")
        conn.execute(f"RELEASE {SAVEPOINT}")
        return [NOT_APPLIED.format(str(e) or type(e).__name__)]
    conn.execute(f"RELEASE {SAVEPOINT}")
    return summary(rewritten, kept)


KEPT_SHOWN = 10


def summary(rewritten, kept):
    """The start log's line: what was rewritten, and every start the quests left as they are, by ID, so a quest an
    upstream upgrade changed (which then keeps upstream's text) is seen. Nothing when all are up to date."""
    parts = []
    if rewritten:
        parts.append(f"{rewritten} quests rewritten")
    if kept:
        ids = ", ".join(str(qid) for qid in kept[:KEPT_SHOWN])
        more = f" and {len(kept) - KEPT_SHOWN} more" if len(kept) > KEPT_SHOWN else ""
        parts.append(f"{len(kept)} left as they are (their text differs from upstream's and this file's): {ids}{more}")
    return ["Quest dialogue: " + "; ".join(parts)] if parts else []


def digests(world, data=None, chains=None, current=False):
    """{step or ids: {quest id: digest}} of the text every entry's `set` columns hold, read from a copy of the world that
    has had epic_chains applied (when it lacks the marker): upstream's text on a clean world. With `current`, this fix
    is applied to the copy too, so these are the digests of the file's own text, which the next revision's guard lists
    need; a row the fix leaves with another text is an error, not a wrong digest. The world itself is not changed."""
    data = data if data is not None else load_data()
    chains = chains if chains is not None else epic_chains.load_data()
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        copy = os.path.join(tmp, "world.db")
        shutil.copyfile(world, copy)
        conn = sqlite3.connect(copy)
        try:
            with conn:
                for line in epic_chains.apply(conn):
                    if line.startswith("Epic chains: not applied"):
                        raise RuntimeError(line)
            if current:
                _apply_on_copy(conn, data, chains)
            for entry in data.get("quests", []):
                columns = sorted(entry["set"])
                out[label(entry)] = {}
                for qid in _quests(entry, chains)[1].values():
                    row = conn.execute(f"SELECT {', '.join(columns)} FROM DataQuest WHERE ID=?", (qid,)).fetchone()
                    if row is not None:
                        out[label(entry)][str(qid)] = digest(list(row))
        finally:
            conn.close()
    return out


def _apply_on_copy(conn, data, chains):
    """Applies the file to the copy `digests` reads, and checks that every row now holds the file's text."""
    with conn:
        for line in apply(conn, data=data, chains=chains):
            if line.startswith("Quest dialogue: not applied"):
                raise RuntimeError(line)
    for qid, columns, values, _guard in _plan(conn, data, chains):
        row = conn.execute(f"SELECT {', '.join(columns)} FROM DataQuest WHERE ID=?", (qid,)).fetchone()
        if row is not None and [value or "" for value in row] != values:
            raise RuntimeError(f"quest {qid} does not hold the file's text after the fix (its guard lacks the digest "
                               "of the world's text, or its stages differ from the file's)")


def own_digests(data, chains):
    """{quest id: digest} of the file's own current text for each quest of every entry, computed from the file alone.
    Without a world the stage counts of a per-stage list can't be checked; that is fine for a digest."""
    out = {}
    for entry in data.get("quests", []):
        names, by_name = _quests(entry, chains)
        columns = sorted(entry["set"])
        resolved = {column: resolve(column, entry["set"][column], names, {name: None for name in names})
                    for column in columns}
        for name, qid in by_name.items():
            out[str(qid)] = digest([resolved[column][name] for column in columns])
    return out


def unsealed(data, chains):
    """The quest IDs whose current text's digest is not in their guard list."""
    own = own_digests(data, chains)
    guards = {qid: set(guard) for entry in data.get("quests", []) for qid, guard in entry.get("guard", {}).items()}
    return [qid for qid, d in own.items() if d not in guards.get(qid, set())]


def seal(path=DATA_FILE, chains=None):
    """Appends the digest of the file's own current text to each quest's guard list (if it isn't there) and rewrites
    the file in its format; returns the quest IDs it appended to."""
    data = load_data(path)
    chains = chains if chains is not None else epic_chains.load_data()
    own = own_digests(data, chains)
    added = []
    for entry in data.get("quests", []):
        guard = entry.setdefault("guard", {})
        for qid in [str(q) for q in _quests(entry, chains)[1].values()]:
            if own[qid] not in guard.setdefault(qid, []):
                guard[qid].append(own[qid])
                added.append(qid)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return added


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Quest texts in the world data: seal the guard lists, print digests.")
    ap.add_argument("--seal", action="store_true",
                    help="append the digest of the file's own current text to each quest's guard list (run it after "
                         "editing the text, then commit)")
    ap.add_argument("--digests", metavar="WORLD.db",
                    help="print {step or ids: {quest id: digest}} of the text each entry's set columns hold in the "
                         "world, after the epic chains (upstream's text on a clean world); needed for a new entry and when "
                         "an entry's set of columns changes")
    ap.add_argument("--current", action="store_true",
                    help="with --digests: apply this file to the copy first, printing the digests of the file's own text")
    a = ap.parse_args(argv)
    if a.seal == bool(a.digests):
        ap.error("give --seal or --digests WORLD.db")
    if a.current and not a.digests:
        ap.error("--current goes with --digests")
    if a.seal:
        added = seal()
        print(f"sealed: {len(added)} digests added" + (f" (quests {', '.join(added)})" if added else ""))
        return 0
    print(json.dumps(digests(a.digests, current=a.current), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

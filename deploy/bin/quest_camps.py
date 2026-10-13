#!/usr/bin/env python3
"""Quest camps upstream archived, copied back into the world: the company the period gave a quest's target.

Upstream's classic setup moved every generic spawn last edited in 2021 or later out of the Mob table into
offline_classic165_removed_mobs ("Post-legacy generic neutral spawn excluded from the server 1.65 authority"). With them
went camps the period's quest walkthroughs describe: the Tylwyth Teg rangers around Delfina ("by the fire, linked to 2
rangers", 2002), the isolationist camp of the level-45 courier, the Ellyll village around the level-48 seer, and
Lieutenant Grimarth at Sir Dillus's tower. `hdc spawns restore` brings back none of them at the owner's level 20, and
never all: it leaves capitalised names and the levels above its maximum archived. quest_camps.json, beside this file, lists each camp's rows by Mob_ID, with the
names they must carry and why.

world_fixes.py calls apply() inside its transaction, before mob_fixes.py (which then moves rows of these camps), under
its own savepoint: if it fails it is rolled back alone, apply() returns only the "not applied" line, and the other
fixes and the start go on. A camp is copied once per world: it records the marker "quest-camp:<key>" in the fork table
fork_world_fixes, so rows the owner removes later stay removed, and a camp added to the file later is copied on a world
that has the others. The rows keep their Mob_IDs and stay in the archive (as epic_chains.py copies Lord Elidyn's camp);
a row already in Mob is left as it is. Rows missing from both, or archived under another name, are named in the
start log; a camp none of whose rows the world has (in Mob or the archive, under any name) is skipped without a word
(and tried again at the next start). `hdc spawns restore` at a high --max-level can bring back some of a camp's
lowercase-named rows and list them in fork_restored_mobs, which a later restore, `hdc spawns undo` and the quest-twin
removal delete; once the camp is copied, its rows leave that list and stay.
"""
import datetime
import json
import os

SAVEPOINT = "quest_camps"
ARCHIVE = "offline_classic165_removed_mobs"
MARKER_TABLE = "fork_world_fixes"
RESTORED = "fork_restored_mobs"  # spawns.py's list of the rows `hdc spawns restore` brought back
MARKER = "quest-camp:{}"
NOT_APPLIED = "Quest camps: not applied ({}); the camps stay in upstream's archive"
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quest_camps.json")


def load_data(path=DATA_FILE):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check(camp):
    """A camp entry's fields; a bad entry raises ValueError."""
    for field in ("key", "name", "why"):
        if not isinstance(camp.get(field), str) or not camp[field].strip():
            raise ValueError(f"camp {camp.get('key') or camp.get('name') or '?'}: no {field}")
    for field in ("names", "ids"):
        values = camp.get(field)
        if not isinstance(values, list) or not values or not all(isinstance(v, str) and v for v in values):
            raise ValueError(f"camp {camp['key']}: {field} must be a list of names")


def apply(conn, now=None, data=None):
    """Copy every camp not yet copied in this world; returns the summary line, the "not applied" line, or nothing.

    Inside an open transaction (world_fixes.py's), nothing here commits; on a connection with none open, the savepoint
    is the transaction, and its release commits it."""
    tables = {name.lower() for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "mob" not in tables or ARCHIVE.lower() not in tables:
        return []
    now = now or _now()
    data = data if data is not None else load_data()
    conn.execute(f"SAVEPOINT {SAVEPOINT}")
    try:
        conn.execute(f"CREATE TABLE IF NOT EXISTS {MARKER_TABLE} (FixId TEXT PRIMARY KEY, AppliedUtc TEXT NOT NULL)")
        columns = ", ".join(f'"{name}"' for _, name, *_ in conn.execute('PRAGMA table_info("Mob")'))
        copied, missing = [], []
        for camp in data["camps"]:
            check(camp)
            marker = MARKER.format(camp["key"])
            if conn.execute(f"SELECT 1 FROM {MARKER_TABLE} WHERE FixId=?", (marker,)).fetchone():
                continue
            names = [name.lower() for name in camp["names"]]
            marks = ", ".join("?" * len(camp["ids"]))
            archived = {mob_id for (mob_id,) in conn.execute(
                f"SELECT Mob_ID FROM {ARCHIVE} WHERE Mob_ID IN ({marks}) "
                f"AND lower(Name) IN ({', '.join('?' * len(names))})", (*camp["ids"], *names))}
            live = {mob_id for (mob_id,) in conn.execute(f"SELECT Mob_ID FROM Mob WHERE Mob_ID IN ({marks})", camp["ids"])}
            known = {mob_id for (mob_id,) in conn.execute(f"SELECT Mob_ID FROM {ARCHIVE} WHERE Mob_ID IN ({marks})", camp["ids"])}
            if not known and not live:
                continue  # none of the camp is in this world (another world, or a test's): not this world's camp
            gone = [mob_id for mob_id in camp["ids"] if mob_id not in archived and mob_id not in live]
            n = 0
            for mob_id in camp["ids"]:
                if mob_id in archived:
                    n += conn.execute(f"INSERT INTO Mob ({columns}) SELECT {columns} FROM {ARCHIVE} WHERE Mob_ID=? "
                                      "AND Mob_ID NOT IN (SELECT Mob_ID FROM Mob)", (mob_id,)).rowcount
            conn.execute(f"INSERT INTO {MARKER_TABLE} (FixId, AppliedUtc) VALUES (?, ?)", (marker, now))
            if RESTORED.lower() in tables:  # rows `hdc spawns restore` brought back are the camp's now
                conn.execute(f"DELETE FROM {RESTORED} WHERE Mob_ID IN ({marks})", camp["ids"])
            if n:
                copied.append(f"{camp['name']} ({n})")
            if gone:
                missing.append(f"{camp['name']} ({', '.join(gone)})")
    except Exception as e:  # any failure: undo the whole step, and let the other fixes and the start go on
        conn.execute(f"ROLLBACK TO {SAVEPOINT}")
        conn.execute(f"RELEASE {SAVEPOINT}")
        return [NOT_APPLIED.format(str(e) or type(e).__name__)]
    conn.execute(f"RELEASE {SAVEPOINT}")
    if not copied and not missing:
        return []
    parts = []
    if copied:
        parts.append("copied back from upstream's archive: " + ", ".join(copied))
    if missing:
        parts.append("not in the archive as named: " + ", ".join(missing))
    return ["Quest camps: " + "; ".join(parts)]


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

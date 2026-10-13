"""The starting locations that were wrong for the period, moved to the period's towns, from start_towns.json beside this
file.

In the period (1.65) a new character's race and base class fixed its starting town: it appeared beside its base-class
trainer (Mythic's list on Stratics, 2001-09-13; Prima, 2002). Upstream's StartupLocation rows match that for 47 of the
56 race and base-class starts; the file moves the other nine (owner's decisions 2026-10-13, research
start-locations-2026-10-13): the Briton Mage, three Seers and the Elf Stalker to their period towns, and the Shrouded
Isles base classes of the classic races (Briton Disciple, Troll Mystic, Celt and Firbolg Forester) to their SI city,
the only start they had before patch 1.72. Four final-class rows follow (Highlander Scout, Elf Blademaster and
Champion, Norseman Healer): no new character uses them while start_as_base_class turns a stock client's final class
into its base class before the town is picked, but the bots, stored with a final class, start from them. Only new
characters (and bots) are affected; existing characters keep their location and bind.

Like mob_fixes.py it has no marker. At every start a row of the entry's race and class still at upstream's spot
(Region, X, Y, Z and Heading, the five values the fix sets) moves to the period's spot; one already there is up to
date; one at neither is the owner's (or an upstream upgrade's), left alone and named in the start log at every start.
A race and class with no row is skipped. Both spots are in the file and no other row is read: the three Seers form a
cycle, each standing where another race's Seer belongs. world_fixes.py calls apply() inside its transaction, under its
own savepoint: if it fails it is rolled back alone, apply() returns only the "not applied" line, and the other fixes
and the start go on.

The file:
  {"moves": [{"race": 1, "class": 18, "name": "Briton Mage", "town": "Adribard's Retreat (Avalon Marsh)",
              "upstream": [region, x, y, z, heading], "period": [region, x, y, z, heading],
              "copied_from_row": 12, "why": "..."}]}
- race and class: the row's RaceID and ClassID; one entry each.
- upstream: the spot upstream's 0.35 world has. period: the spot to set, copied from the row (StartupLoc_ID in that
  world, copied_from_row) that already stands in the period town beside the right trainer, so no spot is invented.
- name and town: what the start log says, with no commas (the log lists them with commas); why: the sources, dated.
"""
import datetime
import json
import os
import re

SAVEPOINT = "start_towns"
NOT_APPLIED = "Start towns: not applied ({}); the starting locations stay where they are"
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "start_towns.json")
COLUMNS = ("StartupLoc_ID", "RaceID", "ClassID", "Region", "XPos", "YPos", "ZPos", "Heading")


def load_data(path=DATA_FILE):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def check(data):
    """Raise ValueError naming the first thing wrong with the file."""
    moves = data.get("moves")
    if not isinstance(moves, list) or not moves:
        raise ValueError("no moves")
    seen = set()
    for n, entry in enumerate(moves, 1):
        what = f"move {n}" + (f" ({entry['name']})" if isinstance(entry.get("name"), str) and entry["name"] else "")
        for field in ("name", "town"):
            if not isinstance(entry.get(field), str) or not entry[field].strip() or "," in entry[field]:
                raise ValueError(f"{what}: no {field}, or a {field} with a comma")
        if not isinstance(entry.get("why"), str) or not re.search(r"\d{4}-\d\d-\d\d", entry["why"]):
            raise ValueError(f"{what}: no why with its date")
        for field in ("race", "class", "copied_from_row"):
            if not _is_int(entry.get(field)) or entry[field] <= 0:
                raise ValueError(f"{what}: {field} must be a positive number")
        for field in ("upstream", "period"):
            spot = entry.get(field)
            if not isinstance(spot, list) or len(spot) != 5 or not all(_is_int(v) for v in spot):
                raise ValueError(f"{what}: {field} must be [region, x, y, z, heading]")
        if entry["upstream"] == entry["period"]:
            raise ValueError(f"{what}: upstream's spot is already at the period's")
        if (entry["race"], entry["class"]) in seen:
            raise ValueError(f"{what}: race {entry['race']} and class {entry['class']} twice")
        seen.add((entry["race"], entry["class"]))


def _columns(conn):
    return {name.lower() for _, name, *_ in conn.execute('PRAGMA table_info("StartupLocation")')}


def apply(conn, now=None, data=None):
    """Move each row still at upstream's spot to the period's; returns the summary line, the "not applied" line, or
    nothing. Inside an open transaction (world_fixes.py's), nothing here commits."""
    have = _columns(conn)
    if not {c.lower() for c in COLUMNS} <= have:
        return []  # no StartupLocation table, or not upstream's
    now = now or _now()
    conn.execute(f"SAVEPOINT {SAVEPOINT}")
    try:
        data = data if data is not None else load_data()
        check(data)
        stamp = ", LastTimeRowUpdated=?" if "lasttimerowupdated" in have else ""
        moved, kept = [], []
        for entry in data["moves"]:
            upstream, period = tuple(entry["upstream"]), tuple(entry["period"])
            rows = conn.execute("SELECT StartupLoc_ID, Region, XPos, YPos, ZPos, Heading FROM StartupLocation "
                                "WHERE RaceID=? AND ClassID=? ORDER BY StartupLoc_ID",
                                (entry["race"], entry["class"])).fetchall()
            ids = [row[0] for row in rows if tuple(row[1:]) == upstream]
            kept += [f"{entry['name']} (StartupLocation {row[0]})" for row in rows
                     if tuple(row[1:]) not in (upstream, period)]
            if ids:
                conn.execute(f"UPDATE StartupLocation SET Region=?, XPos=?, YPos=?, ZPos=?, Heading=?{stamp} "
                             f"WHERE StartupLoc_ID IN ({', '.join('?' * len(ids))})",
                             (*period, *([now] if stamp else []), *ids))
                moved.append((entry, len(ids)))
    except Exception as e:  # any failure: undo this fix only, and let the other fixes and the start go on
        conn.execute(f"ROLLBACK TO {SAVEPOINT}")
        conn.execute(f"RELEASE {SAVEPOINT}")
        return [NOT_APPLIED.format(str(e) or type(e).__name__)]
    conn.execute(f"RELEASE {SAVEPOINT}")
    return summary(moved, kept)


def summary(moved, kept):
    """The start log's line: each move, and every start the rows left alone. Nothing when all are up to date."""
    parts = []
    if moved:
        rows = sum(n for _, n in moved)
        names = ", ".join(f"{entry['name']}{f' ({n} rows)' if n > 1 else ''} to {entry['town']}" for entry, n in moved)
        parts.append(f"{rows} starting location{'' if rows == 1 else 's'} moved to the period's towns: {names}")
    if kept:
        parts.append(f"{len(kept)} left {'as it is' if len(kept) == 1 else 'as they are'} (at neither upstream's spot "
                     f"nor the period's): {', '.join(kept)}")
    return ["Start towns: " + "; ".join(parts)] if parts else []


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

#!/usr/bin/env python3
"""Upstream's world update (db-<version>.json in an OfflineDAoC game patch), applied to a world database.

A release upstream ships as a patch on a full base release (0.37b: the 0.36b game plus the 0.37 game patch) has no
world file of its own: its clean world is the base's clean world plus the patch's world update, a JSON row diff. This
applies it as upstream's patcher does (source/tools/OfflineDaoc.Patcher/Program.cs, class WorldUpdate, lines 264-396
at v0.37b):
- new tables and their indexes (CREATE ... IF NOT EXISTS), and new columns where the table lacks them (names compared
  without case);
- per table: INSERT OR IGNORE of the added rows; UPDATE ... SET every column WHERE every compared column IS its old
  value; DELETE ... WHERE the same; compared = every column but the update's IgnoreColumns and the table's
  IgnoreCompare (names without case);
- values as Program.cs Value() reads them: null, text, integers (int64, past it a double), doubles, true and false as
  1 and 0, {"$b64": ...} as a blob;
- all in one transaction with the offline_patch_log row (Version, AppliedUtc in .NET's "o" format, Notes), so the
  update runs once, and upstream's patcher, should it ever see this world, knows the update is in.
Unlike the patcher, which leaves a row "as the game had it" when it does not match, this is strict like upstream's
check of a new patch against the released base (source/tools/make_patch.py check_world_update, `assert kept == 0`,
line 189): any row that does not apply rolls everything back and raises WorldUpdateError naming the rows. The log
table is created inside the transaction too, so a refused update leaves the file byte for byte as it was. A world
that already has the log row is left alone, so a second run changes nothing. Nothing in the patch is executed.

build_world() makes a release's clean world for an edition, as init_world (a new world) and world_admin
(fetch-clean, upgrade-world) need it: the base's world, and with a patch, a copy of it with the patch's world update.
It says so in its own words ("... applied to the new clean copy"), not the patcher's "World data updated to ...":
the owner's world is never the one it changes, and an upgrade whose import then fails leaves that world as it was.
"""
import base64
import datetime
import os
import re
import shutil
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "..", "tools", "linux")]

from odaoc_fetch import FetchError  # noqa: E402

INT64_MIN, INT64_MAX = -(1 << 63), (1 << 63) - 1


class WorldUpdateError(FetchError):
    """The world update does not fit the world; the world is unchanged."""


def _q(name):
    return '"' + name.replace('"', '""') + '"'


def _if_not_exists(sql):
    # Program.cs Exec(..., ignoreExists: true): three case-insensitive replacements, in this order.
    for old, new in (("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS "), ("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS "),
                     ("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS ")):
        sql = re.sub(re.escape(old), lambda m, new=new: new, sql, flags=re.IGNORECASE)
    return sql


def value(v):
    """A JSON value of the update as the SQLite value Program.cs WorldUpdate.Value() binds."""
    if v is None or isinstance(v, (str, float)):
        return v
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, int):
        return v if INT64_MIN <= v <= INT64_MAX else float(v)
    if isinstance(v, dict) and set(v) == {"$b64"}:
        return base64.b64decode(v["$b64"], validate=True)
    raise ValueError(f"unexpected value in the world update: {v!r}")


def _applied(con, version):
    if con.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND lower(name)='offline_patch_log'").fetchone()[0] == 0:
        return False
    return con.execute("SELECT count(*) FROM offline_patch_log WHERE Version=?", (version,)).fetchone()[0] > 0


def _rows(con, update):
    """Apply the update's tables, columns and rows; returns (counts, the rows that did not apply)."""
    con.execute("CREATE TABLE IF NOT EXISTS offline_patch_log (Version TEXT PRIMARY KEY, AppliedUtc TEXT, Notes TEXT)")
    for t in update["NewTables"]:
        con.execute(_if_not_exists(t["Create"]))
        for index in t.get("Indexes", []):
            con.execute(_if_not_exists(index))
    for col in update["NewColumns"]:
        have = {r[1].lower() for r in con.execute(f"PRAGMA table_info({_q(col['Table'])})")}
        if col["Column"].lower() not in have:
            con.execute(f"ALTER TABLE {_q(col['Table'])} ADD COLUMN {_q(col['Column'])} {col['Decl']}")
    ignored = {c.lower() for c in update["IgnoreColumns"]}
    counts, missed = {"added": 0, "changed": 0, "removed": 0}, []
    for t in update["Tables"]:
        table, cols = t["Table"], t["Columns"]
        skip = ignored | {c.lower() for c in t.get("IgnoreCompare", [])}
        cmp = [i for i, c in enumerate(cols) if c.lower() not in skip]
        where = " AND ".join(f"{_q(cols[i])} IS ?" for i in cmp)
        key = [cols.index(k) for k in t["Key"]]

        def miss(op, row):
            missed.append(f"{table} {op} " + ", ".join(f"{cols[i]}={row[i]!r}" for i in key))

        insert = f"INSERT OR IGNORE INTO {_q(table)} ({','.join(_q(c) for c in cols)}) VALUES ({','.join('?' * len(cols))})"
        for row in t["Insert"]:
            if con.execute(insert, [value(v) for v in row]).rowcount == 1:
                counts["added"] += 1
            else:
                miss("insert", row)
        change = f"UPDATE {_q(table)} SET {','.join(_q(c) + '=?' for c in cols)} WHERE {where}"
        for row in t["Update"]:
            if con.execute(change, [value(v) for v in row["New"]] + [value(row["Old"][i]) for i in cmp]).rowcount > 0:
                counts["changed"] += 1
            else:
                miss("update", row["Old"])
        remove = f"DELETE FROM {_q(table)} WHERE {where}"
        for row in t["Delete"]:
            if con.execute(remove, [value(row[i]) for i in cmp]).rowcount > 0:
                counts["removed"] += 1
            else:
                miss("delete", row)
    return counts, missed


def apply(db, update, version, log=print):
    """Apply `update` (a parsed db-<version>.json) to the world database `db` as patch `version`. Returns
    {"added", "changed", "removed"} counts, or None when the world already has this version's update. Raises
    WorldUpdateError, with the world unchanged, when any row does not apply or the update cannot be applied."""
    con = sqlite3.connect(db, isolation_level=None)  # autocommit; the one transaction is begun and ended here
    try:
        if _applied(con, version):
            log(f"World data: already updated to {version}.")
            return None
        con.execute("BEGIN")
        try:
            counts, missed = _rows(con, update)
            if missed:
                shown = ", ".join(missed[:10]) + (f", and {len(missed) - 10} more" if len(missed) > 10 else "")
                raise WorldUpdateError(f"the {version} world update does not fit this world: {len(missed)} of its rows "
                                       f"did not apply ({shown}); the world is unchanged")
            now = datetime.datetime.now(datetime.timezone.utc)
            applied_utc = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}0Z"  # .NET DateTime "o"
            con.execute("INSERT INTO offline_patch_log (Version, AppliedUtc, Notes) VALUES (?, ?, ?)",
                        (version, applied_utc, ""))
            con.execute("COMMIT")
        except BaseException as e:
            if con.in_transaction:
                con.execute("ROLLBACK")
            if isinstance(e, (sqlite3.Error, KeyError, TypeError, ValueError)):
                raise WorldUpdateError(f"the {version} world update could not be applied ({e}); "
                                       "the world is unchanged") from e
            raise
    finally:
        con.close()
    log(f"World data updated to {version}: {counts['added']} added, {counts['changed']} changed, "
        f"{counts['removed']} removed.")
    return counts


def build_world(release, edition, dest, cache, log=print):
    """Put the release's clean world for `edition` at dest. Returns what fetching the base's world returned ("ok",
    or "skip" when the file was there and right). Without a patch, dest is the base's world itself (verified). With
    one, the patch's world update is fetched and checked first, then the base's world into the folder `cache`
    (verified, and kept, so the next build downloads no world), and a copy of it gets the update and only then
    replaces dest. A patched world has no published hash to resume by (its log row holds the time), so it is
    rebuilt from the cached base each time."""
    world_db = release.edition(edition)["world_db"]
    if not release.lock.get("patch"):
        return release.extract(world_db, dest)
    version, update = release.world_update(edition)
    base = os.path.join(cache, release.root.rstrip("/"), world_db)
    got = release.extract(world_db, base)
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    tmp = dest + ".building"
    try:
        shutil.copyfile(base, tmp)
        counts = apply(tmp, update, version, log=lambda line: None)
        for side in ("-journal", "-wal", "-shm"):
            if os.path.exists(tmp + side):
                raise WorldUpdateError(f"the {version} world update left {os.path.basename(tmp + side)} behind")
        os.replace(tmp, dest)
        if counts is None:
            log(f"The new clean copy already had upstream's {version} world update.")
        else:
            log(f"Upstream's {version} world update applied to the new clean copy: {counts['added']} added, "
                f"{counts['changed']} changed, {counts['removed']} removed.")
    finally:
        for path in (tmp, tmp + "-journal", tmp + "-wal", tmp + "-shm"):
            if os.path.exists(path):
                os.remove(path)
    return got

"""Points along the bridge decks of the horse routes, from route_fixes.json beside this file.

A stable horse (GameTaxi) skips pathfinding and moves in a straight line, height included, from one point of its route
to the next (PathPoints rows, ordered by Step). Most routes cross the Magical Bridge north of Camelot, the Prydwen Keep
bridge and nine other bridges on bank-to-bank segments with no point on the bridge, so the line runs up to 456
under the walkway and the client draws the horse swimming in the river below (owner 2026-10-13). Each entry of the file
is one such crossing: two consecutive points of a route as upstream ships them, and the points to put between them
along the walkway, 15 over its height. The heights were measured on the owner's own client from the bridges' height
grids (research horse-bridges-2026-10-13); only the numbers are ours, no client file ships.

Like mob_fixes.py it has no marker. At every start a crossing whose two points still follow each other, at upstream's
values, gets its points; one that already has them is up to date; on a route that is in the world but no longer has
the segment (the owner or an upstream upgrade changed it), the crossing is left alone and named in the start log. A
route not in the world is skipped. world_fixes.py calls apply() inside its transaction, under its own savepoint: if it
fails it is rolled back alone, apply() returns only the "not applied" line, and the other fixes and the start go on.

The file:
  {"why": "...", "bridges": {"pkb": "the Prydwen Keep bridge (Camelot Hills)", ...},
   "crossings": [{"route": "HS_...", "bridge": "pkb", "from": [x, y, z], "to": [x, y, z],
                  "points": [[x, y, z], ...], "deck": [[x, y, w], ...]}]}
- points: between from and to, on the line between them and in order. Each takes the MaxSpeed of `to` (a segment's
  speed is its end point's), WaitTime 0, and a PathPoints_ID made from the crossing and its index (point_id), so the
  added rows can be found. The route's later points move up by their number. When a later release changes a
  crossing's points (the heights tuned after a ride), its rows from the earlier release, still in one run between
  from and to, are replaced by the new ones; moved or split up, they are the owner's and the crossing is named.
- deck: the walkway's heights along the crossing, which the tests hold the fixed line to.
- bridges: the names the start log uses, with no commas (the log lists them with commas).
"""
import datetime
import json
import math
import os
import re
import uuid

SAVEPOINT = "route_fixes"
NOT_APPLIED = "Route fixes: not applied ({}); the horse routes keep the points they have"
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "route_fixes.json")
ON_LINE = 3  # how far off the straight line between from and to a point may be (rounding)
OWN_MAX = 64  # point_id indexes below this mark the rows this fix added; no crossing has more points
SHOWN = 10


def load_data(path=DATA_FILE):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def point_id(crossing, index):
    """The PathPoints_ID of the crossing's added point number `index` (from 0)."""
    key = ":".join(["hearthdaoc-route-fix", crossing["route"].lower(), *map(str, crossing["from"]),
                    *map(str, crossing["to"]), str(index)])
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def _is_point(value):
    return (isinstance(value, list) and len(value) == 3
            and all(isinstance(v, int) and not isinstance(v, bool) for v in value))


def check(data):
    """Raise ValueError naming the first thing wrong with the file."""
    if not isinstance(data.get("why"), str) or not re.search(r"\d{4}", data["why"]):
        raise ValueError("no why with its date")
    bridges = data.get("bridges")
    if not isinstance(bridges, dict) or not all(isinstance(v, str) and v.strip() for v in bridges.values()):
        raise ValueError("bridges must name each bridge")
    for n, crossing in enumerate(data.get("crossings") or [], 1):
        route = crossing.get("route")
        what = f"crossing {n}" + (f" ({route})" if isinstance(route, str) and route else "")
        if not isinstance(route, str) or not route.strip():
            raise ValueError(f"{what}: no route")
        if crossing.get("bridge") not in bridges:
            raise ValueError(f"{what}: unknown bridge {crossing.get('bridge')}")
        for end in ("from", "to"):
            if not _is_point(crossing.get(end)):
                raise ValueError(f"{what}: {end} must be [x, y, z]")
        pts = crossing.get("points")
        if not isinstance(pts, list) or not pts or not all(_is_point(p) for p in pts):
            raise ValueError(f"{what}: no points")
        if len(pts) > OWN_MAX:
            raise ValueError(f"{what}: more than {OWN_MAX} points")
        if not isinstance(crossing.get("deck"), list) or not all(_is_point(p) for p in crossing["deck"]):
            raise ValueError(f"{what}: deck must be a list of [x, y, w]")
        (ax, ay, _), (bx, by, _) = crossing["from"], crossing["to"]
        length = math.dist((ax, ay), (bx, by))
        if length == 0:
            raise ValueError(f"{what}: from and to are the same spot")
        last = 0.0
        for x, y, _ in pts:
            along = ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / length
            off = abs((x - ax) * (by - ay) - (y - ay) * (bx - ax)) / length
            if off > ON_LINE:
                raise ValueError(f"{what}: point ({x}, {y}) is off the line, by {off:.0f}")
            if not last < along < length:
                raise ValueError(f"{what}: the points must be in order between from and to")
            last = along


def _rows(conn, route):
    return conn.execute("SELECT PathID, Step, X, Y, Z, MaxSpeed, PathPoints_ID FROM PathPoints WHERE PathID=? "
                        "ORDER BY Step", (route,)).fetchall()


def _has_routes(conn):
    have = {name.lower() for _, name, *_ in conn.execute('PRAGMA table_info("PathPoints")')}
    return {"pathid", "step", "x", "y", "z", "maxspeed", "waittime", "pathpoints_id"} <= have


def apply(conn, now=None, data=None):
    """Give each crossing still at upstream's values its deck points; returns the summary line, the "not applied"
    line, or nothing. Inside an open transaction (world_fixes.py's), nothing here commits."""
    if not _has_routes(conn):
        return []
    now = now or _now()
    conn.execute(f"SAVEPOINT {SAVEPOINT}")
    try:
        data = data if data is not None else load_data()
        check(data)
        stamp = "LastTimeRowUpdated" if "lasttimerowupdated" in {
            name.lower() for _, name, *_ in conn.execute('PRAGMA table_info("PathPoints")')} else None
        changed, kept = [], []
        for crossing in data.get("crossings") or []:
            rows = _rows(conn, crossing["route"])
            if not rows:
                continue  # the route isn't in this world
            coords = [tuple(r[2:5]) for r in rows]
            start, end, pts = tuple(crossing["from"]), tuple(crossing["to"]), [tuple(p) for p in crossing["points"]]
            label = f"{crossing['route']} ({data['bridges'][crossing['bridge']]})"
            ours = {point_id(crossing, index) for index in range(OWN_MAX)}
            mine = [i for i, row in enumerate(rows) if row[6] in ours]
            if mine:  # this fix's rows, from this release or an earlier one with other numbers
                first, last = mine[0], mine[-1]
                if (mine != list(range(first, last + 1)) or first == 0 or last + 1 == len(rows)
                        or coords[first - 1] != start or coords[last + 1] != end):
                    kept.append(label)  # moved or split up since: the owner's now
                    continue
                if coords[first:last + 1] == pts:
                    continue
                conn.execute(f"DELETE FROM PathPoints WHERE PathPoints_ID IN ({', '.join('?' * len(mine))})",
                             [rows[i][6] for i in mine])
                conn.execute("UPDATE PathPoints SET Step=Step-? WHERE PathID=? AND Step>?",
                             (len(mine), rows[first][0], rows[last][1]))
                rows = _rows(conn, crossing["route"])
                coords = [tuple(r[2:5]) for r in rows]
            done = [i for i in range(len(coords)) if coords[i:i + len(pts) + 2] == [start, *pts, end]]
            pending = [i for i in range(len(coords) - 1) if coords[i] == start and coords[i + 1] == end]
            if done and not pending:
                continue
            if len(pending) != 1 or done:
                kept.append(label)
                continue
            path_id, step = rows[pending[0]][0], rows[pending[0]][1]
            speed = rows[pending[0] + 1][5]
            conn.execute("UPDATE PathPoints SET Step=Step+? WHERE PathID=? AND Step>?", (len(pts), path_id, step))
            for index, (x, y, z) in enumerate(pts):
                columns = "PathID, Step, X, Y, Z, MaxSpeed, WaitTime, PathPoints_ID" + (f", {stamp}" if stamp else "")
                values = (path_id, step + 1 + index, x, y, z, speed, 0, point_id(crossing, index)) + ((now,) if stamp else ())
                conn.execute(f"INSERT INTO PathPoints ({columns}) VALUES ({', '.join('?' * len(values))})", values)
            changed.append(crossing)
    except Exception as e:  # any failure: undo this fix only, and let the other fixes and the start go on
        conn.execute(f"ROLLBACK TO {SAVEPOINT}")
        conn.execute(f"RELEASE {SAVEPOINT}")
        return [NOT_APPLIED.format(str(e) or type(e).__name__)]
    conn.execute(f"RELEASE {SAVEPOINT}")
    return summary(data, changed, kept)


def _plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


def summary(data, changed, kept):
    """The start log's line: the crossings given points, by bridge, and every start the crossings left alone. Nothing
    when all are up to date."""
    parts = []
    if changed:
        routes = {c["route"].lower() for c in changed}
        counts = {key: sum(1 for c in changed if c["bridge"] == key) for key in data["bridges"]}
        by_bridge = ", ".join(f"{n} on {data['bridges'][key]}" for key, n in counts.items() if n)
        parts.append(f"{_plural(len(changed), 'bridge crossing', 'bridge crossings')} of "
                     f"{_plural(len(routes), 'horse route', 'horse routes')} given points on the deck: {by_bridge}")
    if kept:
        more = f" and {len(kept) - SHOWN} more" if len(kept) > SHOWN else ""
        parts.append(f"{len(kept)} left {'as it is' if len(kept) == 1 else 'as they are'} (the route no longer has "
                     f"that segment): {', '.join(kept[:SHOWN])}{more}")
    return ["Route fixes: " + "; ".join(parts)] if parts else []


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

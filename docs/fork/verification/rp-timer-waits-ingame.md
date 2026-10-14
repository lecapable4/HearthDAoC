# Gamebots come back worth realm points (stage 1): in-game checks

For the owner, after the release with the realm point waits is installed (`./hdc update`). The design is in the
[spec](../specs/2026-10-13-rp-timer-waits-design.md); these are its checks (section 10.4) and its log reads (10.5).
Write what you saw on each check's "Result:" line: pass or fail, and anything odd. Log lines pasted in are welcome.

- Date:
- Release (`HEARTHDAOC_TAG` in `~/hearthdaoc/.env`):

What changes: a gamebot killed in RvR or a battleground and released waits at a safe spot (its realm's arrival point in
a battleground, its bind in the frontier, or its warband's slot at the border keep). It leaves when its time left is no
more than its trip back, so it arrives just as it is worth realm points again, 300 s after its last death. The timer
itself is unchanged. A bot resurrected where it fell fights on. Waiting bots rest and rebuff and fight back when they
or a realm-mate near them are attacked, but don't run at enemies they only see. In this stage every battleground bot
leaves at its own moment (no waves).

## Reading the server log

Each event writes one line starting `HEARTHDAOC_RP_WAIT` to the server log. `./hdc logs` keeps only the last 200
lines, so read the log files themselves, on the server, from `~/hearthdaoc`. The server starts a new log file at
midnight (and at 100 MB) and keeps a week of them, so every command here reads them all, oldest first:

```bash
docker exec hearthdaoc-server sh -c 'cat $(ls -tr /data/logs/server*)' | grep HEARTHDAOC_RP_WAIT
```

Add `| tail -20` for the latest lines, or `| grep 'bot=<name>'` for one bot. Each line starts with its date and time
(`MM/dd HH:mm:ss`). `docker exec hearthdaoc-server ls /data/logs` lists the files: `server.log` is today's, and the
older ones carry their date.

| Line | Written when | What to read |
|---|---|---|
| `action=died` | a gamebot is killed by another realm (a player, an enemy bot, a guard or a pet), with the switch on or off | `worth=yes` (the kill paid realm points) or `worth=no` (it paid none); `sinceLastDeath=` seconds since its previous death (`none`: no earlier death since the server started); `region=` |
| `action=start` | a wait starts | `case=` (`battleground`, `frontier`, `siege` or `warband`); `worthIn=` seconds until it is worth points; `trip=` seconds to walk back; `leaveIn=` seconds until it leaves; `spot=`; `group=` for a warband |
| `action=skip` | a released bot still worth nothing doesn't wait | `reason=`: `trip` (it arrives worth points anyway), `other-region`, `moved-away`, `relic` or `no-target` |
| `action=leave` | a wait ends | `waited=` seconds; `reason=`: `due` (its time), `died`, `player-group`, `off`, `changed`, `called`, `battle`, `moved-away`, `relic`, `no-target` or `other-region` |

Regions: the battlegrounds are 253 Abermenai (levels 15-19), 252 Thidranki (20-24), 251 Murdaigean (25-29) and 250
Caledonia (30-35); the frontiers are 1 (Albion), 100 (Midgard) and 200 (Hibernia).

The arrival points outside the portal keeps, the same in all four battlegrounds: Albion 36428, 51260 (Z 3952), Midgard
53150, 26093 (Z 4263), Hibernia 19714, 19085 (Z 4094). Inside a battleground a GM gets to Albion's with
`/jump to 36428 51260 3952`.

Every line counted by kind, case, reason and worth, for checks 7 and 9 and the reads at the end:

```bash
docker exec hearthdaoc-server sh -c 'cat $(ls -tr /data/logs/server*)' | grep HEARTHDAOC_RP_WAIT |
  awk '{ k = ""; for (i = 1; i <= NF; i++) if ($i ~ /^(action|case|reason|worth)=/) k = k " " $i; n[k]++ }
       END { for (k in n) print n[k] k }' | sort -k2
```

To read only part of the log, for example a few hours with the switch on and then a few with it off, add a time filter
right after the `grep` of any command here, with the month/day and hour:minute you switched. For example, the counts
from 18:00 to 21:00 on 14 October:

```bash
docker exec hearthdaoc-server sh -c 'cat $(ls -tr /data/logs/server*)' | grep HEARTHDAOC_RP_WAIT |
  awk '$0 >= "10/14 18:00" && $0 < "10/14 21:00"' |
  awk '{ k = ""; for (i = 1; i <= NF; i++) if ($i ~ /^(action|case|reason|worth)=/) k = k " " $i; n[k]++ }
       END { for (k in n) print n[k] k }' | sort -k2
```

## The checks

### 1. The update

`./hdc update` lists `HEARTHDAOC_BOT_RP_TIMER_WAIT` among the new settings added to `.env`, and `.env` has
`HEARTHDAOC_BOT_RP_TIMER_WAIT=on`. The first start after the update prints "Bot realm point timer wait: on":

```bash
grep HEARTHDAOC_BOT_RP_TIMER_WAIT ~/hearthdaoc/.env
docker logs hearthdaoc-server 2>&1 | grep 'Bot realm point timer wait'
```

Result:

### 2. Battleground: a death and its wait

With a character of a battleground's levels, kill an enemy bot near the central keep. The log shows its `died …
worth=yes`, then about 30 s later `start case=battleground` with `trip=11` (an Albion bot) or about `trip=43` (Midgard,
Hibernia).

Its `leave reason=due` comes about the `start`'s `leaveIn` seconds after the `start` (`waited=` on the `leave` line),
or up to about 12 s later: a standing bot thinks only every few seconds, and a rebuff can take the turn it was woken
for. A bot still fighting at its moment leaves later, on its first turn after the fight ends (10 s after the last
blow); that is expected, never early.

Result:

### 3. At the arrival point

Go to that realm's arrival point outside its portal keep (the coordinates above). Its waiting bots stand there, apart,
each at its own spot about 160-330 from the point, and don't run at you, even one just arriving through the teleporter.
Hit one: it, and its realm-mates within 1,000, fight back; after the fight they walk back to their spots and wait on (a
fight writes no `leave`).

Result:

### 4. Leaving, and worth points in the field

At its `leave` a bot walks out on its own (no waves in this stage). Kill it in the field: you get realm points, with no
"has been killed recently and is worth no realm points!" message, and the log shows `died … worth=yes`.

As in check 2, each `leave reason=due` comes about its `start`'s `leaveIn` after the `start`, or up to about 12 s
later, unless it was fighting at its moment.

Result:

### 5. A kill while it waits

Kill a bot while it waits: you get the "worth no realm points" message, as expected, and the log shows `died …
worth=no` and, at the same death, `leave reason=died`. After its next release it gets a new `start`. A warband member
resurrected at its slot instead gets no new `start`.

(A bot killed by a monster while it waits also gets `leave reason=died`, with no `died` line: `died` lines are only for
kills by another realm.)

Result:

### 6. A player's invite

Invite a waiting bot into your group: `leave reason=player-group`. Remove it from the group before its timer runs out:
it doesn't walk back to its spot.

Result:

### 7. Frontier, over a day of play

In the counts (above): `start case=frontier` and `start case=siege` for defenders near their home binds (Fensalir
Faste, Mjollner Faste, Dun Ailinne …); `skip … reason=other-region` for invaders, who release in their capital;
`start case=warband` with a `group=`, one per released member at the warband's slots, and one `leave` each when the
warband sets out together:

```bash
docker exec hearthdaoc-server sh -c 'cat $(ls -tr /data/logs/server*)' | grep 'case=warband'
```

Result:

### 8. At a home bind

Hit one waiting bot at a home bind: it fights back; its solo neighbours do not. That is expected: the bots' threat scan
is off at a bind, so only a bot that is attacked answers.

Result:

### 9. Off

Set `HEARTHDAOC_BOT_RP_TIMER_WAIT=off` in `~/hearthdaoc/.env`, then `./hdc up`: the start prints "Bot realm point
timer wait: off" (`docker logs hearthdaoc-server 2>&1 | grep 'Bot realm point timer wait'`). From then on, no `start`
lines; `died` lines still come; bots run straight back as before. Note the time, for the comparison below. Afterwards
set it back to `on` and `./hdc up` again.

Result:

## Reading the log over hours

Run these from `~/hearthdaoc` after some hours of play. A server restart ends every wait without a `leave` line (the
timer and the waits are kept in memory only), so lines from before a restart can show a `start` with no `leave`.

**Every `start` has exactly one `leave`.** The last two numbers should be 0 (except across a restart, or at the start
of the oldest log file kept, a week back). The middle one
is how many bots are sitting out at the last line read; to see it at another moment, add a time filter such as
`awk '$0 < "10/14 20:00"' |` after the `grep`.

```bash
docker exec hearthdaoc-server sh -c 'cat $(ls -tr /data/logs/server*)' | grep -E 'HEARTHDAOC_RP_WAIT action=(start|leave) ' |
  awk '{ id = $0; sub(/.* id=/, "", id); sub(/ .*/, "", id)
         if ($0 ~ / action=start /) { starts++; if (open[id]) twice++; open[id] = 1 }
         else { leaves++; if (!open[id]) lone++; open[id] = 0 } }
       END { for (id in open) if (open[id]) still++
             printf "%d starts, %d leaves, %d sitting out; ", starts, leaves, still
             printf "%d starts with no leave before the next, %d leaves with no start\n", twice, lone }'
```

**Kills that paid nothing:** the share of `worth=no` among `died`, in total and per region (250-253 the
battlegrounds; 1, 100 and 200 the frontiers). Compare a few hours with the switch on against a few hours with it off
(the time filter, above).

```bash
docker exec hearthdaoc-server sh -c 'cat $(ls -tr /data/logs/server*)' | grep 'HEARTHDAOC_RP_WAIT action=died ' |
  awk '{ r = $0; sub(/.* region=/, "", r); sub(/ .*/, "", r); all[r]++; total++
         if ($0 ~ / worth=no /) { no[r]++; none++ } }
       END { for (r in all) printf "region %s: %d of %d kills paid nothing\n", r, no[r], all[r]
             printf "all regions: %d of %d kills paid nothing\n", none, total }' | sort
```

**Before this release:** the same share from the `RVR_BOT_KILLED` lines the server already writes (one per gamebot
killed by another realm): a bot `id=` killed again within 300 s of its previous line paid nothing. It is a lower bound:
deaths to monsters and neutral guards restart the timer too, but write no such line. Use the time filter to stop at the
update.

```bash
docker exec hearthdaoc-server sh -c 'cat $(ls -tr /data/logs/server*)' | grep 'RVR_BOT_KILLED ' |
  awk 'BEGIN { split("0 31 59 90 120 151 181 212 243 273 304 334", before, " ") }
       { split(substr($0, 1, 14), t, /[\/ :]/)
         s = ((before[t[1] + 0] + t[2]) * 24 + t[3]) * 3600 + t[4] * 60 + t[5]
         id = $0; sub(/.* id=/, "", id); sub(/ .*/, "", id)
         total++; if ((id in last) && s - last[id] < 300) none++; last[id] = s }
       END { printf "%d of %d kills paid nothing (the same bot killed again within 300 s)\n", none, total }'
```

**The cost:** `waited=` on the `leave reason=due` lines. In the battlegrounds about 230-260 s (est.): Albion about
259 s, Midgard and Hibernia about 227 s.

```bash
docker exec hearthdaoc-server sh -c 'cat $(ls -tr /data/logs/server*)' | grep 'HEARTHDAOC_RP_WAIT action=leave ' |
  awk '/ reason=due/ { c = $0; sub(/.* case=/, "", c); sub(/ .*/, "", c)
         r = $0; sub(/.* realm=/, "", r); sub(/ .*/, "", r)
         w = $0; sub(/.* waited=/, "", w); sub(/ .*/, "", w); n[c " " r]++; sum[c " " r] += w }
       END { for (k in n) printf "%s: %d waits, %d s on average\n", k, n[k], sum[k] / n[k] }' | sort
```

**What remains** (kills that still pay nothing), from the counts above:

- bots killed again at their spot, for example by players camping an arrival point: `leave reason=died`;
- bots resurrected where they fell: they never wait, so their next death can be `worth=no`;
- waits ended early: `leave` reasons other than `due`;
- released bots that didn't wait: the `skip` reasons.

#!/usr/bin/env python3
"""Online stats, phase 1 (lab branch, karimialireza36-cmd/doctor-dns).

What has to hold, on the relay's side: nginx's usage line carries $status at
its end; each connection is counted as carried (ok), refused for a name port
443 does not carry (sni_denied) or failed for no exit (exit_failed); a line
from before $status counts its bytes as it always did and gets no verdict;
the per-exit count still reads the last address, not the status; one address
asking for names without end cannot grow the count without bound; and what
was not delivered is kept, what was delivered cleared.

On the panel's side: verdicts become catalogue services, and no host name is
kept; online five minutes are marked by the same test as last_seen; a day's
minutes, sessions and peak are built from them, the same each time it runs;
what is past keeping goes (verdicts 30 days, days 90); and the three admin
routes answer only a key with admin rights, a reseller's only for its own.
"""
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
fails = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label +
          ((" - " + repr(detail)) if detail != "" and not cond else ""))
    if not cond:
        fails.append(label)


def load(path, mod):
    spec = importlib.util.spec_from_loader(
        mod, importlib.machinery.SourceFileLoader(mod, os.path.join(HERE, "..", path)))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def read(rel):
    with open(os.path.join(HERE, "..", rel), encoding="utf-8") as fh:
        return fh.read()


sync = load("templates/smartdns-sync", "sync")
sync.log = lambda *a: None
sync.sh = lambda *a: None
sync.is_single = lambda: False
sync.current_exit_ip = lambda: "198.51.100.7"

print("nginx's line")
conf = read("templates/relay-nginx.conf")
check("the usage line ends with $status, after the exit it went to",
      "$bytes_received $upstream_addr $status';" in conf)
check("the installer carries the same line",
      "$bytes_received $upstream_addr $status';" in read("doctor-dns.sh"))

print("how a connection ended")
check("200 through an exit is ok", sync.verdict_of("127.0.0.1:18443", "200") == "ok")
check("the closed port is sni_denied, whatever the status",
      sync.verdict_of("127.0.0.1:9", "502") == "sni_denied"
      and sync.verdict_of("127.0.0.1:9", "200") == "sni_denied")
check("502 and 503 are exit_failed",
      sync.verdict_of("127.0.0.1:18443, 198.51.100.7:443", "502") == "exit_failed"
      and sync.verdict_of("198.51.100.7:443", "503") == "exit_failed")
check("a line with no status, or another status, says nothing",
      sync.verdict_of("198.51.100.7:443", None) is None
      and sync.verdict_of("-", "400") is None and sync.verdict_of("-", "500") is None)
check("a status is only taken from a line long enough to have one",
      sync.split_status("a 443 n 1 1 x:443 200".split()) == ("a 443 n 1 1 x:443".split(), "200")
      and sync.split_status("a 443 n 1 1 x:443".split()) == ("a 443 n 1 1 x:443".split(), None)
      and sync.split_status("a 443 1 1".split())[1] is None)

print("the relay's count")
tmp = tempfile.mkdtemp()
sync.USAGE_LOG = os.path.join(tmp, "usage")
sync.USAGE_TAKEN = sync.USAGE_LOG + ".taken"
with open(sync.USAGE_TAKEN, "w") as fh:
    fh.write("203.0.113.5 443 gs2.playstation.net 900 100 127.0.0.1:18443 200\n"
             "203.0.113.5 443 gs2.playstation.net 50 50 127.0.0.1:18443 200\n"
             "203.0.113.5 443 www.example.org 0 517 127.0.0.1:9 502\n"
             "203.0.113.5 443 gs2.playstation.net 0 300"
             " 127.0.0.1:18443, 198.51.100.7:443 502\n"
             "203.0.113.5 80 - 10 10 198.51.100.7:80 200\n"
             "203.0.113.6 443 old.example 7 3 198.51.100.7:443\n"
             "garbage\n")
sync.USAGE_PENDING.clear()
sync.EXIT_PENDING.clear()
sync.VERDICT_PENDING.clear()
services = sync.take_usage()
check("bytes by name are what they were",
      services == {"203.0.113.5": {"gs2.playstation.net": 1400, "www.example.org": 517,
                                   ":80": 20},
                   "203.0.113.6": {"old.example": 10}}, services)
check("each connection is counted by how it ended, with its bytes",
      sync.VERDICT_PENDING == {"203.0.113.5": {
          "gs2.playstation.net": {"ok": [2, 1100], "exit_failed": [1, 300]},
          "www.example.org": {"sni_denied": [1, 517]},
          ":80": {"ok": [1, 20]}}}, sync.VERDICT_PENDING)
check("the per-exit count reads the exit, not the status",
      sync.EXIT_PENDING["203.0.113.5"]["198.51.100.7"] == [100 + 50 + 300 + 10, 900 + 50 + 10]
      and sync.EXIT_PENDING["203.0.113.6"] == {"198.51.100.7": [3, 7]},
      sync.EXIT_PENDING)
check("the line is deleted once read", not os.path.exists(sync.USAGE_TAKEN))

print("an address asking for names without end")
sync.VERDICT_PENDING.clear()
for i in range(sync.VERDICT_NAMES_MAX + 50):
    sync.count_verdict("203.0.113.9", "n%d.example" % i, "sni_denied", 1)
per = sync.VERDICT_PENDING["203.0.113.9"]
check("the names stop at the limit, the rest under _other",
      len(per) == sync.VERDICT_NAMES_MAX + 1 and per["_other"]["sni_denied"] == [50, 50])
sync.VERDICT_PENDING.clear()

print("delivery")
src = read("templates/smartdns-sync")
check("the sync sends the count and clears it only once the panel has it",
      'payload["verdicts"]' in src
      and src.index('answer = post("/sync", payload)')
      < src.index("        VERDICT_PENDING.clear()"))

# ================================================================ the panel
panel = load("templates/smartdns-panel", "panel")
panel.log = lambda *a: None
panel.log_exception = lambda *a: None
panel.print = lambda *a, **k: None
db_path = os.path.join(tmp, "panel.db")
store = panel.Store(db_path)
store.run("INSERT INTO templates (name, is_default, created_at) VALUES ('کامل', 1, ?)",
          (panel.now(),))
u = store.create_user(111, "ali", "علی")
store.run("UPDATE users SET status = 'active' WHERE id = ?", (u["id"],))
panel.register_ip(store, u["id"], "203.0.113.5")
catalogue = [{"key": "psn", "label": "پلی‌استیشن",
              "groups": [{"domains": ["playstation.net"]}]}]
panel.CATALOGUE[:] = catalogue

print("verdicts in the panel")
panel.record_verdicts(store, {
    "203.0.113.5": {"gs2.playstation.net": {"ok": [2, 1100], "exit_failed": [1, 300]},
                    "www.example.org": {"sni_denied": [1, 517]},
                    "x.example": {"made_up": [9, 9], "ok": ["bad", 1]}, "y": "bad"},
    "198.51.100.1": {"gs2.playstation.net": {"ok": [5, 5]}}}, catalogue)
rows = {(r["service"], r["verdict"]): (r["conns"], r["bytes"])
        for r in store.q("SELECT * FROM usage_verdict")}
check("verdicts are kept per customer, per service, per day",
      rows == {("psn", "ok"): (2, 1100), ("psn", "exit_failed"): (1, 300),
               ("_other", "sni_denied"): (1, 517)}, rows)
kept = json.dumps([dict(r) for r in store.q("SELECT * FROM usage_verdict")])
check("no host name is kept", "playstation.net" not in kept and "example.org" not in kept)

print("online days")
check("a day's stretches: minutes, sessions split by a ten-minute gap, first and last",
      panel.online_stretches(["2026-11-28T10:00", "2026-11-28T10:05", "2026-11-28T10:15",
                              "2026-11-28T10:30"]) == (20, 2, "10:00", "10:35")
      and panel.online_stretches([]) == (0, 0, None, None))
store.fold_counters("r1", {"203.0.113.5": 1000})
check("a trickle does not mark the five minutes",
      not store.one("SELECT 1 FROM online_5m"))
store.fold_counters("r1", {"203.0.113.5": 1000 + panel.ONLINE_MIN_BYTES})
check("traffic that makes a customer online marks them",
      store.one("SELECT count(*) n FROM online_5m")["n"] == 1)
now_t = datetime.now(timezone.utc)
today = panel.usage_buckets(now_t)["1d"]
yday = panel.usage_buckets(now_t - timedelta(days=1))["1d"]
v = store.create_user(222, "sara", "سارا")
store.run("DELETE FROM online_5m")
for uid, b in ((u["id"], "T20:00"), (u["id"], "T20:05"), (u["id"], "T21:00"),
               (v["id"], "T20:05")):
    store.run("INSERT INTO online_5m (user_id, bucket) VALUES (?, ?)", (uid, yday + b))
panel.build_online(store, now_t)
panel.build_online(store, now_t)
d = store.one("SELECT * FROM online_daily WHERE user_id = ? AND day = ?", (u["id"], yday))
check("yesterday is built from the five minutes, and the same when built again",
      (d["minutes"], d["sessions"], d["first_at"], d["last_at"]) == (15, 2, "20:00", "21:05")
      and store.one("SELECT count(*) n FROM online_daily")["n"] == 2, dict(d))
p = store.one("SELECT * FROM online_peak WHERE day = ?", (yday,))
check("the day's most online at once, with its time", (p["peak"], p["at"]) == (2, "20:05"),
      dict(p))

print("keeping")
old = panel.usage_buckets(now_t - timedelta(days=40))["1d"]
older = panel.usage_buckets(now_t - timedelta(days=100))["1d"]
store.run("INSERT INTO usage_verdict (user_id, day, service, verdict, conns, bytes)"
          " VALUES (?, ?, 'psn', 'ok', 1, 1)", (u["id"], old))
store.run("INSERT INTO online_daily (user_id, day, minutes) VALUES (?, ?, 5)", (u["id"], old))
store.run("INSERT INTO online_daily (user_id, day, minutes) VALUES (?, ?, 5)",
          (u["id"], older))
store.run("INSERT INTO online_peak (day, peak) VALUES (?, 1)", (older,))
store.run("INSERT INTO online_5m (user_id, bucket) VALUES (?, ?)", (u["id"], old + "T10:00"))
panel.prune_usage(store)
check("verdicts go after 30 days, days and peaks after 90, five minutes after two",
      not store.one("SELECT 1 FROM usage_verdict WHERE day = ?", (old,))
      and store.one("SELECT 1 FROM online_daily WHERE day = ?", (old,))
      and not store.one("SELECT 1 FROM online_daily WHERE day = ?", (older,))
      and not store.one("SELECT 1 FROM online_peak WHERE day = ?", (older,))
      and not store.one("SELECT 1 FROM online_5m WHERE bucket = ?", (old + "T10:00",))
      and store.one("SELECT 1 FROM online_daily WHERE day = ?", (yday,)))
check("a customer's rows go with the customer",
      "ON DELETE CASCADE" in read("templates/smartdns-panel").split(
          "CREATE TABLE IF NOT EXISTS usage_verdict")[1].split(");")[0])

print("the admin's routes")
for name, scope, seller in (("boss", "admin", None), ("shop", "customer", None),
                            ("reseller", "admin", 99)):
    store.run("INSERT INTO api_tokens (name, token_hash, scope, admin_id, created_at)"
              " VALUES (?, ?, ?, ?, ?)",
              (name, panel.token_hash("dd_" + name), scope, seller, panel.now()))
panel.BotAPI.store = store
panel.BotAPI.relays = ("198.51.100.4",)
server = panel.BotServer(("127.0.0.1", 0), None, None)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % server.server_address[1]


def call(path, key):
    req = urllib.request.Request(BASE + path)
    req.add_header("Authorization", "Bearer dd_" + key)
    try:
        res = urllib.request.urlopen(req, timeout=10)
        return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


code, got = call("/api/v1/admin/users/%d/activity" % u["id"], "boss")
check("a customer's activity: online now, setup, seven days, games",
      code == 200 and got["online"] is True and got["setup"]["ips"] == 1
      and got["setup"]["game_ok_at"] and len(got["days"]) == 7
      and got["days"][1]["minutes"] == 15
      and [(g["key"], g["ok"], g["exit_failed"]) for g in got["games"]][0] == ("psn", 2, 1)
      and got["games"][0]["label"] == "پلی‌استیشن", got)
code, got = call("/api/v1/admin/online", "boss")
check("who is online now, with today's and yesterday's peaks",
      code == 200 and got["count"] == 1 and got["users"][0]["telegram_id"] == 111
      and got["peaks"]["yesterday"]["peak"] == 2, got)
code, got = call("/api/v1/admin/activity?day=" + yday, "boss")
check("a day across customers: longest online first, peak",
      code == 200 and got["active_users"] == 2 and got["top_users"][0]["minutes"] == 15
      and got["peak"]["peak"] == 2, got)
code, got = call("/api/v1/admin/activity?day=" + today, "boss")
check("  and its games carried, refused and failed",
      code == 200 and got["games_ok"][0]["key"] == "psn"
      and got["games_denied"][0]["key"] == "_other"
      and got["games_failed"][0]["conns"] == 1, got)
check("a day that is not a day is refused",
      call("/api/v1/admin/activity?day=yesterday", "boss")[0] == 400)
check("a customer's key gets none of it",
      all(call(path, "shop")[0] == 403 for path in (
          "/api/v1/admin/online", "/api/v1/admin/activity",
          "/api/v1/admin/users/%d/activity" % u["id"])))
code, got = call("/api/v1/admin/online", "reseller")
check("a reseller's admin key sees only its own customers",
      code == 200 and got["count"] == 0
      and call("/api/v1/admin/users/%d/activity" % u["id"], "reseller")[0] == 404, got)
server.shutdown()

print()
if fails:
    print("%d failed" % len(fails))
    sys.exit(1)
print("all passed")

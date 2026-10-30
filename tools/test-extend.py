#!/usr/bin/env python3
"""Days made up by API: POST /admin/users/{id}/extend.

After an outage the operator's bot gives every paying customer the days they
lost. What has to hold: the days go on top of the end the account already has
(not "now plus N", as the admin panel's box does); reserved plans keep their
turn after the new end; the allowance is untouched; an account whose days ran
out comes back only when asked to ("revive"), and then from now; a suspended
account stays suspended; the expiring notice is due again; the same request
twice with one Idempotency-Key adds the days once; and only an admin key may.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
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
GB = 1024 ** 3


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label +
          ((" - " + detail) if detail and not cond else ""))
    if not cond:
        fails.append(label)


spec = importlib.util.spec_from_loader(
    "panel", importlib.machinery.SourceFileLoader(
        "panel", os.path.join(HERE, "..", "templates", "smartdns-panel")))
panel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(panel)
panel.log = lambda *a: None
panel.print = lambda *a, **k: None

tmp = tempfile.mkdtemp()
store = panel.Store(os.path.join(tmp, "panel.db"))
store.run("INSERT INTO templates (name, is_default, created_at) VALUES ('بازی', 1, ?)",
          (panel.now(),))
store.run("INSERT INTO plans (name, template_id, days, quota_bytes, price, created_at)"
          " VALUES ('بازی یک ماهه', 1, 30, ?, 150000, ?)", (5 * GB, panel.now()))
for name, scope in (("shop", "customer"), ("boss", "admin")):
    store.run("INSERT INTO api_tokens (name, token_hash, scope, created_at)"
              " VALUES (?, ?, ?, ?)", (name, panel.token_hash("dd_" + name), scope,
                                       panel.now()))

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def account(name, status, ends, used=GB, warned=0):
    store.run("INSERT INTO users (username, created_at, status, plan_id, expires_at,"
              " quota_bytes, used_bytes, warned) VALUES (?, ?, ?, 1, ?, ?, ?, ?)",
              (name, panel.now(), status, ends.isoformat(timespec="seconds") if ends else None,
               5 * GB, used, warned))
    return store.user_by_username(name)["id"]


panel.BotAPI.store = store
panel.BotAPI.relays = ("198.51.100.4",)
server = panel.BotServer(("127.0.0.1", 0), None, None)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d/api/v1" % server.server_address[1]


def call(uid, body, key="dd_boss", idem=None):
    req = urllib.request.Request(BASE + "/admin/users/%d/extend" % uid, method="POST",
                                 data=json.dumps(body).encode())
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Content-Type", "application/json")
    if idem:
        req.add_header("Idempotency-Key", idem)
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def row(uid):
    return store.one("SELECT * FROM users WHERE id = ?", (uid,))


def ends(uid):
    return panel.parse_ts(row(uid)["expires_at"])


print("only an admin key")
a = account("a", "active", NOW + timedelta(days=10))
code, res = call(a, {"days": 3}, key="dd_shop")
check("a customer key is refused", code == 403 and res["error"] == "admin_only")

print("days on top of what is left")
code, res = call(a, {"days": 3, "note": "اختلال"})
check("200 and the new end", code == 200 and res["ok"] and res["days"] == 3
      and not res["revived"], str(res))
check("ten days left become thirteen", ends(a) == NOW + timedelta(days=13), str(ends(a)))
check("the allowance is untouched", row(a)["quota_bytes"] == 5 * GB
      and row(a)["used_bytes"] == GB)
check("the message names the days", "۳" in res["message"] or "3" in res["message"],
      res["message"])

print("the expiring notice is due again")
w = account("w", "active", NOW + timedelta(days=2), warned=panel.WARNED_EXPIRING | 1)
call(w, {"days": 7})
check("the expiring bit goes, the others stay",
      row(w)["warned"] == 1, str(row(w)["warned"]))

print("reserved plans keep their turn")
r = account("r", "active", NOW + timedelta(days=5))
store.run("INSERT INTO reserved_plans (user_id, plan_id, created_at) VALUES (?, 1, ?)",
          (r, panel.now()))
call(r, {"days": 2})
check("still reserved, the running plan longer",
      store.one("SELECT count(*) c FROM reserved_plans WHERE user_id = ?", (r,))["c"] == 1
      and ends(r) == NOW + timedelta(days=7))

print("statuses")
s = account("s", "suspended", NOW + timedelta(days=4))
code, res = call(s, {"days": 1})
check("a suspended account gets the day and stays suspended",
      code == 200 and row(s)["status"] == "suspended" and ends(s) == NOW + timedelta(days=5))
q = account("q", "over_quota", NOW + timedelta(days=4), used=5 * GB)
call(q, {"days": 1})
check("one out of allowance stays out of allowance", row(q)["status"] == "over_quota")

print("an account whose days ran out")
e = account("e", "expired", NOW - timedelta(days=2))
code, res = call(e, {"days": 3})
check("without revive: 409, nothing changed", code == 409 and res["error"] == "expired"
      and row(e)["status"] == "expired" and ends(e) == NOW - timedelta(days=2), str(res))
code, res = call(e, {"days": 3, "revive": True})
got = ends(e)
check("with revive: active, three days from now", code == 200 and res["revived"]
      and row(e)["status"] == "active"
      and NOW + timedelta(days=3) <= got <= NOW + timedelta(days=3, seconds=30), str(got))
check("revive must be true, not just present",
      call(account("e2", "expired", NOW - timedelta(days=1)),
           {"days": 1, "revive": "yes"})[0] == 409)
# The date has passed but the hourly check has not marked it yet.
late = account("late", "active", NOW - timedelta(minutes=5))
code, res = call(late, {"days": 1})
check("a date already past counts as run out", code == 409)

print("what it refuses")
for bad in ({}, {"days": 0}, {"days": -1}, {"days": 91}, {"days": "x"}):
    code, res = call(a, bad)
    check("days %r: 400" % bad.get("days"), code == 400 and res["error"] == "bad_days")
check("90 days is allowed", call(account("big", "active", NOW + timedelta(days=1)),
                                 {"days": 90})[0] == 200)
n = account("n", "active", None)
code, res = call(n, {"days": 1})
check("an account with no end: 409", code == 409 and res["error"] == "no_end")
code, res = call(99999, {"days": 1})
check("a customer who is not there: 404", code == 404)

print("once, with one Idempotency-Key")
k = account("k", "active", NOW + timedelta(days=10))
call(k, {"days": 3}, idem="comp-1-k")
code, res = call(k, {"days": 3}, idem="comp-1-k")
check("the second copy is answered from memory, the days added once",
      code == 200 and ends(k) == NOW + timedelta(days=13), str(ends(k)))
code, res = call(k, {"days": 4}, idem="comp-1-k")
check("the same key for another request: 422", code == 422)

server.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
print()
if fails:
    print("%d FAILED: %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("all checks passed")

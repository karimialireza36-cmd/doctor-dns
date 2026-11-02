#!/usr/bin/env python3
"""An extra pack of gigabytes by API: POST /admin/users/{id}/quota.

A customer whose allowance ran low buys an extra pack from the operator's bot.
What has to hold: the gigabytes go on top of the allowance the account already
has; the days, the plan and the bytes used are untouched; an account out of
allowance is active again once it has some left; a suspended one stays
suspended; the quota warnings are due again, the expiring one is kept; an
unlimited account and one whose days ran out are refused; the same request
twice with one Idempotency-Key adds the pack once; and only an admin key may.
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
    req = urllib.request.Request(BASE + "/admin/users/%d/quota" % uid, method="POST",
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


def quota(uid):
    return row(uid)["quota_bytes"]


print("only an admin key")
a = account("a", "active", NOW + timedelta(days=10))
code, res = call(a, {"gb": 10}, key="dd_shop")
check("a customer key is refused", code == 403 and res["error"] == "admin_only")

print("gigabytes on top of what is there")
code, res = call(a, {"gb": 10, "note": "بستهٔ ۱۰ گیگ"})
check("200 and the new allowance", code == 200 and res["ok"] and res["gb"] == 10
      and not res["reactivated"] and res["quota_bytes"] == 15 * GB, str(res))
check("five became fifteen", quota(a) == 15 * GB, str(quota(a)))
check("days and bytes used untouched", ends(a) == NOW + timedelta(days=10)
      and row(a)["used_bytes"] == GB and row(a)["plan_id"] == 1)
check("the message names the gigabytes", "10" in res["message"] or "۱۰" in res["message"],
      res["message"])

print("out of allowance")
q = account("q", "over_quota", NOW + timedelta(days=4), used=5 * GB, warned=1 | 2)
code, res = call(q, {"gb": 10})
check("back to active", code == 200 and res["reactivated"] and row(q)["status"] == "active",
      str(res))
check("the quota warnings are due again", row(q)["warned"] == 0, str(row(q)["warned"]))
deep = account("deep", "over_quota", NOW + timedelta(days=4), used=20 * GB)
code, res = call(deep, {"gb": 1})
check("still nothing left: stays out of allowance", code == 200 and not res["reactivated"]
      and row(deep)["status"] == "over_quota" and quota(deep) == 6 * GB, str(res))

print("other statuses and warnings")
s = account("s", "suspended", NOW + timedelta(days=4))
code, res = call(s, {"gb": 5})
check("a suspended account gets the pack and stays suspended",
      code == 200 and row(s)["status"] == "suspended" and quota(s) == 10 * GB)
w = account("w", "active", NOW + timedelta(days=2), warned=panel.WARNED_EXPIRING | 1)
call(w, {"gb": 5})
check("the expiring bit stays, the quota bit goes", row(w)["warned"] == panel.WARNED_EXPIRING,
      str(row(w)["warned"]))

print("what it refuses")
e = account("e", "expired", NOW - timedelta(days=2))
code, res = call(e, {"gb": 5})
check("days ran out: 409, nothing changed", code == 409 and res["error"] == "expired"
      and quota(e) == 5 * GB, str(res))
late = account("late", "active", NOW - timedelta(minutes=5))
check("a date already past counts as run out", call(late, {"gb": 5})[0] == 409)
store.run("INSERT INTO users (username, created_at, status, plan_id, expires_at, quota_bytes,"
          " used_bytes) VALUES ('u', ?, 'active', 1, ?, 0, 0)",
          (panel.now(), (NOW + timedelta(days=5)).isoformat(timespec="seconds")))
u = store.user_by_username("u")["id"]
code, res = call(u, {"gb": 5})
check("unlimited: 409, still unlimited", code == 409 and res["error"] == "unlimited"
      and quota(u) == 0, str(res))
for bad in ({}, {"gb": 0}, {"gb": -1}, {"gb": 1001}, {"gb": "x"}):
    code, res = call(a, bad)
    check("gb %r: 400" % bad.get("gb"), code == 400 and res["error"] == "bad_gb")
check("1000 GB is allowed", call(account("big", "active", NOW + timedelta(days=1)),
                                 {"gb": 1000})[0] == 200)
code, res = call(99999, {"gb": 1})
check("a customer who is not there: 404", code == 404)

print("once, with one Idempotency-Key")
k = account("k", "active", NOW + timedelta(days=10))
call(k, {"gb": 30}, idem="pack-1-k")
code, res = call(k, {"gb": 30}, idem="pack-1-k")
check("the second copy is answered from memory, the pack added once",
      code == 200 and quota(k) == 35 * GB, str(quota(k)))
code, res = call(k, {"gb": 60}, idem="pack-1-k")
check("the same key for another request: 422", code == 422)

server.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
print()
if fails:
    print("%d FAILED: %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("all checks passed")

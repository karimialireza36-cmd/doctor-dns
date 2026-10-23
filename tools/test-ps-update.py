#!/usr/bin/env python3
"""PlayStation system updates go direct, never through the relay.

A PS5 system update is about 1.2-1.3 GB. Under the playstation.net line it was
routed: it ate a plan's volume and cost the operator relay and exit traffic,
although Sony's update CDN answers an Iranian address directly (200 from an
Iranian datacenter, October 2026). What has to hold:

- the main resolver bypasses update.playstation.net (longer than the routed
  playstation.net, so dnsmasq's longest match lets it win);
- the catalogue has it as an opt-in bypass group, so no template routes it
  unless an operator ticks it, and the default template does not;
- the rest of PlayStation - store, account, online, game downloads - is untouched.
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
fails = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label +
          ((" - " + str(detail)[:400]) if detail and not cond else ""))
    if not cond:
        fails.append(label)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


print("PlayStation system updates")
lines = read("common/bypass.conf").splitlines()
check("the main resolver asks for update.playstation.net directly",
      "server=/update.playstation.net/#" in lines)
check("the installer carries the same line",
      "#server=/update.playstation.net/#" in read("doctor-dns.sh").splitlines())
services = json.loads(read("domains/services.json"))["services"]
bypass = next(s for s in services if s["key"] == "bypass")
grp = next((g for g in bypass["groups"] if g["key"] == "playstation-update"), None)
check("an opt-in bypass group holds exactly that name",
      grp is not None and grp["domains"] == ["update.playstation.net"] and grp.get("opt_in"))
check("  not locked, so an operator can still route it if Sony ever blocks Iran",
      grp is not None and not grp.get("locked"))
routed = {d for s in services if s["key"] != "bypass" for g in s["groups"] for d in g["domains"]}
check("no routed group names an update host",
      not [d for d in routed if d == "update.playstation.net" or d.endswith(".update.playstation.net")])
ps = next(s for s in services if s["key"] == "playstation")
online = next(g for g in ps["groups"] if g["key"] == "online")
download = next(g for g in ps["groups"] if g["key"] == "download")
check("PlayStation online still routes playstation.net (store, account, online)",
      "playstation.net" in online["domains"] and not online.get("opt_in"))
check("game downloads keep their own group",
      "gst.prod.dl.playstation.net" in download["domains"])
listed = [l.strip() for l in read("domains/domains.txt").splitlines()]
check("the shared routed list does not name an update host",
      not [l for l in listed if l.endswith("update.playstation.net")])
en = json.loads(read("domains/i18n-en.json"))
check("label and note have English", grp is not None and grp["label"] in en and grp["note"] in en)

print()
print("FAILED: %d" % len(fails) if fails else "all ok")
sys.exit(1 if fails else 0)

#!/usr/bin/env python3
"""Rockstar through the service.

What has to hold: Rockstar's sign-in and game services (ros., cloud. and
prod-locator-cloud.rockstargames.com) resolve directly, on the main resolver
and in every template - routed, ROS sees the exit's address while the console
plays from Iran's and refuses it (0x50060190). rockstargames.com itself stays
routed.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
fails = []
NAMES = ["ros.rockstargames.com", "cloud.rockstargames.com", "prod-locator-cloud.rockstargames.com"]


def check(label, cond):
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond:
        fails.append(label)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


lines = read("common/bypass.conf").splitlines()
for n in NAMES:
    check("the main resolver asks for %s directly" % n, "server=/%s/#" % n in lines)
services = json.loads(read("domains/services.json"))["services"]
group = next(g for s in services if s["key"] == "bypass" for g in s["groups"] if g["key"] == "rockstar")
check("every template does, the group being locked", group["domains"] == NAMES and group.get("locked"))
main = next(g for s in services if s["key"] == "rockstar" for g in s["groups"] if g["key"] == "main")
check("rockstargames.com itself stays routed", "rockstargames.com" in main["domains"])
check("the installer carries it", "#server=/ros.rockstargames.com/#" in read("doctor-dns.sh"))
sys.exit(1 if fails else 0)
